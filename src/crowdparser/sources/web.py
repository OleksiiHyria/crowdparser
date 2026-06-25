from __future__ import annotations
import httpx
from crowdparser.models import RawItem
from crowdparser.sources.base import BaseSource
from crowdparser.config import WebSourceConfig

_JINA_PREFIX = "https://r.jina.ai/"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; crowdparser/0.1)"}


async def _fetch_url(client: httpx.AsyncClient, url: str, use_jina: bool) -> str | None:
    try:
        r = await client.get(url, headers=_HEADERS, follow_redirects=True, timeout=20)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass

    if use_jina:
        try:
            r = await client.get(_JINA_PREFIX + url, headers=_HEADERS, timeout=30)
            if r.status_code == 200:
                return r.text
        except Exception:
            pass

    return None


class WebSource(BaseSource):
    def __init__(self, cfg: WebSourceConfig):
        self._cfg = cfg

    async def fetch(self) -> list[RawItem]:
        items: list[RawItem] = []
        async with httpx.AsyncClient() as client:
            for url in self._cfg.urls:
                text = await _fetch_url(client, url, self._cfg.use_jina)
                if text and len(text) > 100:
                    items.append(RawItem(
                        content=text[:50_000],  # cap at 50k chars
                        source_url=url,
                        source_type="web",
                        metadata={"url": url},
                    ))
        return items
