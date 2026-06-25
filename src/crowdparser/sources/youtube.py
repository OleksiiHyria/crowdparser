from __future__ import annotations
import asyncio
import os
import httpx
from crowdparser.models import RawItem
from crowdparser.sources.base import BaseSource
from crowdparser.config import YouTubeSourceConfig

_INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
_IT_SEARCH  = f"https://www.youtube.com/youtubei/v1/search?key={_INNERTUBE_KEY}"
_IT_BROWSE  = f"https://www.youtube.com/youtubei/v1/browse?key={_INNERTUBE_KEY}"
_IT_PLAYER  = f"https://www.youtube.com/youtubei/v1/player?key={_INNERTUBE_KEY}"
_IT_NEXT    = f"https://www.youtube.com/youtubei/v1/next?key={_INNERTUBE_KEY}"
_DATA_BASE  = "https://www.googleapis.com/youtube/v3"
_CLIENT_CTX = {"client": {"clientName": "WEB", "clientVersion": "2.20240101"}}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _api_key() -> str:
    return os.environ.get("YOUTUBE_API_KEY", "")


async def _post(client: httpx.AsyncClient, url: str, payload: dict) -> dict:
    r = await client.post(url, json=payload, timeout=20)
    r.raise_for_status()
    return r.json()


async def _get(client: httpx.AsyncClient, url: str, params: dict) -> dict:
    r = await client.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


# ── Search ────────────────────────────────────────────────────────────────────

async def _search_data_api(client: httpx.AsyncClient, query: str, limit: int, lang: str) -> list[dict]:
    ids, page_token = [], None
    while len(ids) < limit:
        params = {
            "part": "snippet", "q": query, "type": "video",
            "maxResults": min(50, limit - len(ids)),
            "relevanceLanguage": lang, "key": _api_key(),
        }
        if page_token:
            params["pageToken"] = page_token
        data = await _get(client, f"{_DATA_BASE}/search", params)
        for item in data.get("items", []):
            vid = item.get("id", {}).get("videoId")
            snippet = item.get("snippet", {})
            if vid:
                ids.append({
                    "video_id": vid,
                    "title": snippet.get("title", ""),
                    "channel_title": snippet.get("channelTitle", ""),
                })
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return ids[:limit]


async def _search_innertube(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    ids, continuation = [], None
    while len(ids) < limit:
        payload = (
            {"context": _CLIENT_CTX, "continuation": continuation}
            if continuation else
            {"context": _CLIENT_CTX, "query": query}
        )
        data = await _post(client, _IT_SEARCH, payload)
        contents = []
        if continuation:
            contents = (
                data.get("onResponseReceivedCommands", [{}])[0]
                .get("appendContinuationItemsAction", {})
                .get("continuationItems", [])
            )
        else:
            contents = (
                data.get("contents", {})
                .get("twoColumnSearchResultsRenderer", {})
                .get("primaryContents", {})
                .get("sectionListRenderer", {})
                .get("contents", [{}])[0]
                .get("itemSectionRenderer", {})
                .get("contents", [])
            )
        continuation = None
        for item in contents:
            vr = item.get("videoRenderer", {})
            vid = vr.get("videoId")
            if vid:
                ids.append({
                    "video_id": vid,
                    "title": vr.get("title", {}).get("runs", [{}])[0].get("text", ""),
                    "channel_title": (
                        vr.get("ownerText", {}).get("runs", [{}])[0].get("text", "")
                    ),
                })
                if len(ids) >= limit:
                    break
            ct = item.get("continuationItemRenderer", {})
            if ct:
                continuation = (
                    ct.get("continuationEndpoint", {})
                    .get("continuationCommand", {})
                    .get("token")
                )
        if not continuation:
            break
    return ids[:limit]


async def _search_videos(client: httpx.AsyncClient, query: str, limit: int, lang: str) -> list[dict]:
    if _api_key():
        try:
            return await _search_data_api(client, query, limit, lang)
        except Exception:
            pass
    return await _search_innertube(client, query, limit)


# ── Channel browse ────────────────────────────────────────────────────────────

async def _channel_video_ids(client: httpx.AsyncClient, channel_id: str, limit: int) -> list[dict]:
    payload = {"context": _CLIENT_CTX, "params": "EgIQAQ%3D%3D", "browseId": channel_id}
    try:
        data = await _post(client, _IT_BROWSE, payload)
    except Exception:
        return []
    ids = []
    try:
        tabs = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"]
        for tab in tabs:
            section = (
                tab.get("tabRenderer", {}).get("content", {})
                .get("richGridRenderer", {}).get("contents", [])
            )
            for item in section:
                vr = (
                    item.get("richItemRenderer", {})
                    .get("content", {})
                    .get("videoRenderer", {})
                )
                vid = vr.get("videoId")
                if vid:
                    ids.append({
                        "video_id": vid,
                        "title": vr.get("title", {}).get("runs", [{}])[0].get("text", ""),
                        "channel_id": channel_id,
                    })
                    if len(ids) >= limit:
                        return ids
    except (KeyError, TypeError):
        pass
    return ids


# ── Metadata (title + description) ───────────────────────────────────────────

async def _fetch_metadata_data_api(client: httpx.AsyncClient, video_ids: list[str]) -> dict[str, dict]:
    """Batch fetch metadata via Data API (50 IDs per request)."""
    result = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        try:
            data = await _get(client, f"{_DATA_BASE}/videos", {
                "part": "snippet",
                "id": ",".join(batch),
                "key": _api_key(),
            })
            for item in data.get("items", []):
                vid = item["id"]
                s = item.get("snippet", {})
                result[vid] = {
                    "title": s.get("title", ""),
                    "description": s.get("description", ""),
                    "channel_title": s.get("channelTitle", ""),
                    "tags": s.get("tags", []),
                    "published_at": s.get("publishedAt", ""),
                }
        except Exception:
            pass
    return result


async def _fetch_metadata_innertube(client: httpx.AsyncClient, video_id: str) -> dict:
    """Fetch video metadata via innertube player endpoint (no API key)."""
    try:
        data = await _post(client, _IT_PLAYER, {
            "context": _CLIENT_CTX,
            "videoId": video_id,
        })
        details = data.get("videoDetails", {})
        return {
            "title": details.get("title", ""),
            "description": details.get("shortDescription", ""),
            "channel_title": details.get("author", ""),
            "tags": details.get("keywords", []),
            "published_at": "",
        }
    except Exception:
        return {}


async def _fetch_metadata(client: httpx.AsyncClient, video_ids: list[str]) -> dict[str, dict]:
    if _api_key():
        result = await _fetch_metadata_data_api(client, video_ids)
        if result:
            return result
    # Innertube: one request per video (no batch endpoint without key)
    sem = asyncio.Semaphore(8)
    async def _one(vid):
        async with sem:
            return vid, await _fetch_metadata_innertube(client, vid)
    pairs = await asyncio.gather(*[_one(vid) for vid in video_ids])
    return {vid: meta for vid, meta in pairs if meta}


# ── Comments ──────────────────────────────────────────────────────────────────

async def _fetch_comments_data_api(client: httpx.AsyncClient, video_id: str, limit: int) -> list[str]:
    comments, page_token = [], None
    while len(comments) < limit:
        params = {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": min(100, limit - len(comments)),
            "order": "relevance",
            "key": _api_key(),
        }
        if page_token:
            params["pageToken"] = page_token
        try:
            data = await _get(client, f"{_DATA_BASE}/commentThreads", params)
        except Exception:
            break
        for item in data.get("items", []):
            text = (
                item.get("snippet", {})
                .get("topLevelComment", {})
                .get("snippet", {})
                .get("textOriginal", "")
            )
            if text and len(text) >= 30:
                comments.append(text)
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return comments[:limit]


async def _fetch_comments_innertube(client: httpx.AsyncClient, video_id: str, limit: int) -> list[str]:
    """Fetch comments via innertube next endpoint (no API key)."""
    # First call to get the continuation token for comments
    try:
        data = await _post(client, _IT_NEXT, {
            "context": _CLIENT_CTX,
            "videoId": video_id,
        })
    except Exception:
        return []

    # Find comment continuation token inside itemSectionRenderer.contents
    cont_token = None
    try:
        sections = (
            data.get("contents", {})
            .get("twoColumnWatchNextResults", {})
            .get("results", {})
            .get("results", {})
            .get("contents", [])
        )
        for section in sections:
            for item in section.get("itemSectionRenderer", {}).get("contents", []):
                ct = item.get("continuationItemRenderer", {})
                if ct:
                    cont_token = (
                        ct.get("continuationEndpoint", {})
                        .get("continuationCommand", {})
                        .get("token")
                    )
                    break
            if cont_token:
                break
    except (KeyError, TypeError):
        pass

    if not cont_token:
        return []

    # Fetch comments using continuation
    comments = []
    while len(comments) < limit and cont_token:
        try:
            data = await _post(client, _IT_NEXT, {
                "context": _CLIENT_CTX,
                "continuation": cont_token,
            })
        except Exception:
            break

        cont_token = None
        actions = data.get("onResponseReceivedEndpoints", [])
        for action in actions:
            items = (
                action.get("reloadContinuationItemsCommand", {}).get("continuationItems", [])
                or action.get("appendContinuationItemsAction", {}).get("continuationItems", [])
            )
            for item in items:
                cr = item.get("commentThreadRenderer", {})
                text = (
                    cr.get("comment", {})
                    .get("commentRenderer", {})
                    .get("contentText", {})
                    .get("runs", [{}])[0]
                    .get("text", "")
                )
                if text and len(text) >= 30:
                    comments.append(text)
                    if len(comments) >= limit:
                        break
                # Next page continuation
                ct = item.get("continuationItemRenderer", {})
                if ct:
                    cont_token = (
                        ct.get("continuationEndpoint", {})
                        .get("continuationCommand", {})
                        .get("token")
                    )

    return comments[:limit]


async def _fetch_comments(client: httpx.AsyncClient, video_id: str, limit: int) -> list[str]:
    """Comments require YOUTUBE_API_KEY — innertube switched to commentViewModel (no text in response)."""
    if _api_key():
        try:
            return await _fetch_comments_data_api(client, video_id, limit)
        except Exception:
            pass
    # innertube comment format no longer includes text inline (commentViewModel)
    return []


# ── Transcript ────────────────────────────────────────────────────────────────

def _get_transcript(video_id: str, languages: list[str]) -> str | None:
    from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
    try:
        segs = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
        return " ".join(s["text"] for s in segs)
    except (NoTranscriptFound, TranscriptsDisabled):
        return None
    except Exception:
        return None


# ── Source ────────────────────────────────────────────────────────────────────

class YouTubeSource(BaseSource):
    def __init__(self, cfg: YouTubeSourceConfig):
        self._cfg = cfg

    async def fetch(self) -> list[RawItem]:
        cfg = self._cfg
        seen: set[str] = set()
        video_meta: list[dict] = []

        async with httpx.AsyncClient(timeout=20) as client:
            # 1. Explicit video IDs
            for vid in cfg.video_ids:
                if vid not in seen:
                    seen.add(vid)
                    video_meta.append({"video_id": vid, "title": ""})

            # 2. Channel latest videos
            for ch_id in cfg.channel_ids:
                try:
                    results = await _channel_video_ids(client, ch_id, cfg.channel_limit)
                    for r in results:
                        if r["video_id"] not in seen:
                            seen.add(r["video_id"])
                            video_meta.append(r)
                except Exception:
                    pass

            # 3. Keyword search
            for query in cfg.search_queries:
                try:
                    results = await _search_videos(client, query, cfg.search_limit, cfg.search_lang)
                    for r in results:
                        if r["video_id"] not in seen:
                            seen.add(r["video_id"])
                            r["search_query"] = query
                            video_meta.append(r)
                except Exception:
                    pass

            # 4. Batch-fetch metadata (title, description, tags)
            metadata_map: dict[str, dict] = {}
            if cfg.fetch_metadata and video_meta:
                all_ids = [m["video_id"] for m in video_meta]
                metadata_map = await _fetch_metadata(client, all_ids)
                # Merge into video_meta
                for m in video_meta:
                    extra = metadata_map.get(m["video_id"], {})
                    m.update({k: v for k, v in extra.items() if k not in m or not m[k]})

            # 5. Transcripts + description fallback (concurrent)
            loop = asyncio.get_event_loop()
            sem = asyncio.Semaphore(8)
            items: list[RawItem] = []

            async def _fetch_one(meta: dict) -> RawItem | None:
                async with sem:
                    vid = meta["video_id"]
                    text = await loop.run_in_executor(None, _get_transcript, vid, cfg.languages)
                    fallback = False
                    if not text and cfg.description_fallback:
                        desc = meta.get("description", "")
                        title = meta.get("title", "")
                        if desc or title:
                            text = f"{title}\n\n{desc}".strip()
                            fallback = True
                    if not text:
                        return None
                    return RawItem(
                        content=text,
                        source_url=f"https://www.youtube.com/watch?v={vid}",
                        source_type="youtube",
                        metadata={**meta, "transcript_fallback": fallback},
                    )

            results = await asyncio.gather(*[_fetch_one(m) for m in video_meta])
            items = [r for r in results if r is not None]

            # 6. Comments as separate RawItems
            if cfg.fetch_comments:
                com_sem = asyncio.Semaphore(4)

                async def _fetch_video_comments(meta: dict) -> list[RawItem]:
                    async with com_sem:
                        vid = meta["video_id"]
                        comments = await _fetch_comments(client, vid, cfg.comments_limit)
                        result = []
                        for i, text in enumerate(comments):
                            result.append(RawItem(
                                content=text,
                                source_url=f"https://www.youtube.com/watch?v={vid}&lc=comment_{i}",
                                source_type="youtube_comment",
                                metadata={
                                    "video_id": vid,
                                    "title": meta.get("title", ""),
                                    "channel_title": meta.get("channel_title", ""),
                                },
                            ))
                        return result

                comment_batches = await asyncio.gather(
                    *[_fetch_video_comments(m) for m in video_meta]
                )
                for batch in comment_batches:
                    items.extend(batch)

        return items
