from __future__ import annotations
import asyncio
import os
import httpx
from crowdparser.models import RawItem
from crowdparser.sources.base import BaseSource
from crowdparser.config import YouTubeSourceConfig


_INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
_YT_DATA_SEARCH = "https://www.googleapis.com/youtube/v3/search"
_INNERTUBE_SEARCH = f"https://www.youtube.com/youtubei/v1/search?key={_INNERTUBE_KEY}"
_INNERTUBE_BROWSE = f"https://www.youtube.com/youtubei/v1/browse?key={_INNERTUBE_KEY}"
_CLIENT_CTX = {"client": {"clientName": "WEB", "clientVersion": "2.20240101"}}


# ── Search ────────────────────────────────────────────────────────────────────

async def _search_data_api(query: str, limit: int, lang: str, api_key: str) -> list[dict]:
    """YouTube Data API v3 search — structured, quota-limited (100 units/search)."""
    ids = []
    page_token = None
    async with httpx.AsyncClient(timeout=20) as client:
        while len(ids) < limit:
            params = {
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": min(50, limit - len(ids)),
                "relevanceLanguage": lang,
                "key": api_key,
            }
            if page_token:
                params["pageNextToken"] = page_token
            r = await client.get(_YT_DATA_SEARCH, params=params)
            r.raise_for_status()
            data = r.json()
            for item in data.get("items", []):
                vid = item.get("id", {}).get("videoId")
                title = item.get("snippet", {}).get("title", "")
                if vid:
                    ids.append({"video_id": vid, "title": title})
            page_token = data.get("nextPageToken")
            if not page_token:
                break
    return ids[:limit]


async def _search_innertube(query: str, limit: int) -> list[dict]:
    """Innertube search — no API key, no quota, but fragile JSON structure."""
    ids = []
    continuation = None

    async with httpx.AsyncClient(timeout=20) as client:
        while len(ids) < limit:
            if continuation:
                payload = {"context": _CLIENT_CTX, "continuation": continuation}
            else:
                payload = {"context": _CLIENT_CTX, "query": query}

            r = await client.post(_INNERTUBE_SEARCH, json=payload)
            r.raise_for_status()
            data = r.json()

            # Walk the deeply nested innertube response
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
                title = vr.get("title", {}).get("runs", [{}])[0].get("text", "")
                if vid:
                    ids.append({"video_id": vid, "title": title})
                    if len(ids) >= limit:
                        break
                # Continuation token for next page
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


async def _search_videos(query: str, limit: int, lang: str) -> list[dict]:
    """Try Data API first (if YOUTUBE_API_KEY set), fallback to innertube."""
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if api_key:
        try:
            return await _search_data_api(query, limit, lang, api_key)
        except Exception:
            pass
    return await _search_innertube(query, limit)


# ── Channel browse ────────────────────────────────────────────────────────────

async def _channel_video_ids(channel_id: str, limit: int) -> list[dict]:
    """Fetch recent video IDs from a channel via innertube browse."""
    payload = {
        "context": _CLIENT_CTX,
        "params": "EgIQAQ%3D%3D",   # videos tab
        "browseId": channel_id,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(_INNERTUBE_BROWSE, json=payload)
        r.raise_for_status()
        data = r.json()

    ids = []
    try:
        tabs = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"]
        for tab in tabs:
            contents = tab.get("tabRenderer", {}).get("content", {})
            section = contents.get("richGridRenderer", {}).get("contents", [])
            for item in section:
                vr = (
                    item.get("richItemRenderer", {})
                    .get("content", {})
                    .get("videoRenderer", {})
                )
                vid = vr.get("videoId")
                title = vr.get("title", {}).get("runs", [{}])[0].get("text", "")
                if vid:
                    ids.append({"video_id": vid, "title": title})
                    if len(ids) >= limit:
                        return ids
    except (KeyError, TypeError):
        pass
    return ids


# ── Transcript ────────────────────────────────────────────────────────────────

def _get_transcript(video_id: str, languages: list[str]) -> str | None:
    """Synchronous — runs in executor to avoid blocking the event loop."""
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

        # 1. Explicit video IDs
        for vid in cfg.video_ids:
            if vid not in seen:
                seen.add(vid)
                video_meta.append({"video_id": vid, "title": ""})

        # 2. Channel latest videos
        for ch_id in cfg.channel_ids:
            try:
                results = await _channel_video_ids(ch_id, cfg.channel_limit)
                for r in results:
                    if r["video_id"] not in seen:
                        seen.add(r["video_id"])
                        r["channel_id"] = ch_id
                        video_meta.append(r)
            except Exception:
                pass

        # 3. Keyword search
        for query in cfg.search_queries:
            try:
                results = await _search_videos(query, cfg.search_limit, cfg.search_lang)
                for r in results:
                    if r["video_id"] not in seen:
                        seen.add(r["video_id"])
                        r["search_query"] = query
                        video_meta.append(r)
            except Exception:
                pass

        # 4. Fetch transcripts (concurrent, up to 8 at a time)
        loop = asyncio.get_event_loop()
        sem = asyncio.Semaphore(8)

        async def _fetch_one(meta: dict) -> RawItem | None:
            async with sem:
                vid = meta["video_id"]
                text = await loop.run_in_executor(None, _get_transcript, vid, cfg.languages)
                if not text:
                    return None
                return RawItem(
                    content=text,
                    source_url=f"https://www.youtube.com/watch?v={vid}",
                    source_type="youtube",
                    metadata={k: v for k, v in meta.items()},
                )

        tasks = [_fetch_one(m) for m in video_meta]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]
