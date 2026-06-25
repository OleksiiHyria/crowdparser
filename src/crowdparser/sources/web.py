from __future__ import annotations
import asyncio
import re
import urllib.robotparser
from urllib.parse import urljoin, urlparse
import httpx
from crowdparser.models import RawItem
from crowdparser.sources.base import BaseSource
from crowdparser.config import WebSourceConfig

_JINA_PREFIX = "https://r.jina.ai/"
_UA = "Mozilla/5.0 (compatible; crowdparser/0.1; +https://github.com/OleksiiHyria/crowdparser)"
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "pl,en;q=0.9,uk;q=0.8",
}

# robots.txt cache: domain → RobotFileParser
_robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}


# ── HTML cleaning ─────────────────────────────────────────────────────────────

def _html_to_text(html: str) -> str:
    """HTML → clean plain text.

    Uses trafilatura when available (best article extraction).
    Falls back to aggressive regex tag-stripping.
    """
    try:
        import trafilatura  # type: ignore
        result = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
        )
        if result and len(result) > 100:
            return result
    except ImportError:
        pass

    # Regex fallback: strip scripts/styles then all tags
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&#?\w+;", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ── Forum post extraction ─────────────────────────────────────────────────────

def _extract_posts(html: str, selector: str) -> list[str]:
    """Split HTML into individual posts via CSS selector.

    Requires selectolax (pip install selectolax). Returns [] if unavailable.
    """
    try:
        from selectolax.parser import HTMLParser  # type: ignore
        tree = HTMLParser(html)
        posts = []
        for node in tree.css(selector):
            text = node.text(deep=True, strip=True)
            if text and len(text) > 20:
                posts.append(re.sub(r"\s+", " ", text).strip())
        return posts
    except ImportError:
        return []


# ── Pagination ────────────────────────────────────────────────────────────────

def _find_next_page(html: str, current_url: str, custom_selector: str = "") -> str | None:
    """Detect the next-page URL from raw HTML."""

    # 1. Custom CSS selector (requires selectolax)
    if custom_selector:
        try:
            from selectolax.parser import HTMLParser  # type: ignore
            tree = HTMLParser(html)
            el = tree.css_first(custom_selector)
            if el:
                href = el.attributes.get("href", "")
                if href and not href.startswith(("#", "javascript")):
                    return urljoin(current_url, href)
        except ImportError:
            pass

    # 2. <link rel="next">
    m = re.search(
        r'<link[^>]+rel=["\']next["\'][^>]+href=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    )
    if not m:
        m = re.search(
            r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']next["\']',
            html, re.IGNORECASE,
        )
    if m:
        return urljoin(current_url, m.group(1))

    # 3. <a rel="next"> or <a class="...next...">
    patterns = [
        r'<a[^>]+rel=["\']next["\'][^>]+href=["\']([^"\']+)["\']',
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']next["\']',
        r'<a[^>]+class=["\'][^"\']*\bnext\b[^"\']*["\'][^>]+href=["\']([^"\']+)["\']',
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]+class=["\'][^"\']*\bnext\b[^"\']*["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            href = m.group(1)
            if href and not href.startswith(("#", "javascript")):
                return urljoin(current_url, href)

    return None


# ── Sitemap ───────────────────────────────────────────────────────────────────

def _parse_sitemap(xml: str, filter_str: str = "", limit: int = 100) -> list[str]:
    """Extract URLs from sitemap.xml (handles both <loc> and nested sitemapindex)."""
    urls = [u.strip() for u in re.findall(r"<loc>(.*?)</loc>", xml, re.DOTALL)]
    if filter_str:
        urls = [u for u in urls if filter_str in u]
    return urls[:limit]


# ── robots.txt ────────────────────────────────────────────────────────────────

async def _check_robots(client: httpx.AsyncClient, url: str) -> bool:
    """Returns True if the URL is allowed by robots.txt."""
    parsed = urlparse(url)
    domain = f"{parsed.scheme}://{parsed.netloc}"

    if domain not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"{domain}/robots.txt")
        try:
            r = await client.get(f"{domain}/robots.txt", headers=_HEADERS, timeout=10)
            rp.parse(r.text.splitlines())
        except Exception:
            rp.parse([])  # unavailable → assume allowed
        _robots_cache[domain] = rp

    return _robots_cache[domain].can_fetch(_UA, url)


# ── Fetch layer ───────────────────────────────────────────────────────────────

async def _fetch_direct(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await client.get(url, headers=_HEADERS, follow_redirects=True, timeout=20)
        if r.status_code == 200 and len(r.text) > 100:
            return r.text
    except Exception:
        pass
    return None


async def _fetch_jina(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await client.get(_JINA_PREFIX + url, headers=_HEADERS, timeout=40)
        if r.status_code == 200 and len(r.text) > 100:
            return r.text
    except Exception:
        pass
    return None


async def _fetch(
    client: httpx.AsyncClient,
    url: str,
    use_jina: bool,
    respect_robots: bool,
) -> tuple[str | None, bool]:
    """Returns (content, is_jina). is_jina=True means content is already clean markdown."""
    if respect_robots and not await _check_robots(client, url):
        return None, False

    html = await _fetch_direct(client, url)
    if html:
        return html, False

    if use_jina:
        md = await _fetch_jina(client, url)
        if md:
            return md, True

    return None, False


def _to_clean_text(raw: str, is_jina: bool) -> str:
    """Convert raw content to clean text, capped at 80 000 chars."""
    if is_jina:
        return raw.strip()[:80_000]
    return _html_to_text(raw)[:80_000]


# ── Source ────────────────────────────────────────────────────────────────────

class WebSource(BaseSource):
    def __init__(self, cfg: WebSourceConfig):
        self._cfg = cfg

    async def fetch(self) -> list[RawItem]:
        cfg = self._cfg
        items: list[RawItem] = []
        seen: set[str] = set()

        async with httpx.AsyncClient(timeout=30) as client:

            # ── 0. Sitemap discovery ──────────────────────────────────────────
            all_urls = list(cfg.urls)
            if cfg.sitemap_url:
                raw, is_jina = await _fetch(
                    client, cfg.sitemap_url, cfg.use_jina, respect_robots=False
                )
                if raw:
                    found = _parse_sitemap(raw, cfg.sitemap_filter, cfg.sitemap_limit)
                    all_urls.extend(u for u in found if u not in all_urls)

            # ── 1. Per-URL crawl loop ─────────────────────────────────────────
            for start_url in all_urls:
                if start_url in seen:
                    continue

                page_url: str | None = start_url
                page_num = 0

                while page_url and page_num < cfg.max_pages:
                    if page_url in seen:
                        break
                    seen.add(page_url)

                    if page_num > 0 and cfg.rate_limit_delay > 0:
                        await asyncio.sleep(cfg.rate_limit_delay)

                    raw, is_jina = await _fetch(
                        client, page_url, cfg.use_jina, cfg.respect_robots
                    )
                    if not raw:
                        break

                    # ── Thread structure: one RawItem per post ────────────────
                    if cfg.extract_thread_structure and cfg.post_selector and not is_jina:
                        posts = _extract_posts(raw, cfg.post_selector)
                        if posts:
                            for i, post_text in enumerate(posts):
                                if len(post_text) > 30:
                                    items.append(RawItem(
                                        content=post_text,
                                        source_url=page_url,
                                        source_type="web",
                                        metadata={
                                            "url": page_url,
                                            "post_index": i,
                                            "page": page_num + 1,
                                            "is_op": i == 0,
                                        },
                                    ))
                        else:
                            # selectolax not installed or selector matched nothing
                            text = _to_clean_text(raw, is_jina)
                            if len(text) > 100:
                                items.append(RawItem(
                                    content=text,
                                    source_url=page_url,
                                    source_type="web",
                                    metadata={"url": page_url, "page": page_num + 1},
                                ))
                    else:
                        text = _to_clean_text(raw, is_jina)
                        if len(text) > 100:
                            items.append(RawItem(
                                content=text,
                                source_url=page_url,
                                source_type="web",
                                metadata={"url": page_url, "page": page_num + 1},
                            ))

                    # ── Pagination ────────────────────────────────────────────
                    if not cfg.follow_pagination:
                        break

                    next_url = None
                    if not is_jina:
                        next_url = _find_next_page(raw, page_url, cfg.next_page_selector)

                    page_url = next_url
                    page_num += 1

        return items
