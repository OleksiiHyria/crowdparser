from __future__ import annotations
import asyncio
import httpx
from crowdparser.models import RawItem
from crowdparser.sources.base import BaseSource
from crowdparser.config import YouTubeSourceConfig


_INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
_INNERTUBE_URL = "https://www.youtube.com/youtubei/v1/search"


async def _channel_video_ids(channel_id: str, limit: int) -> list[str]:
    """Fetch recent video IDs from a channel via YouTube's innertube API."""
    payload = {
        "context": {"client": {"clientName": "WEB", "clientVersion": "2.20240101"}},
        "params": "EgIQAQ%3D%3D",  # videos tab filter
        "browseId": channel_id,
    }
    url = f"https://www.youtube.com/youtubei/v1/browse?key={_INNERTUBE_KEY}"
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()

    ids = []
    try:
        tabs = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"]
        for tab in tabs:
            contents = tab.get("tabRenderer", {}).get("content", {})
            section = contents.get("richGridRenderer", {}).get("contents", [])
            for item in section:
                vid = (
                    item.get("richItemRenderer", {})
                    .get("content", {})
                    .get("videoRenderer", {})
                    .get("videoId")
                )
                if vid:
                    ids.append(vid)
                    if len(ids) >= limit:
                        return ids
    except (KeyError, TypeError):
        pass
    return ids


def _get_transcript(video_id: str, languages: list[str]) -> str | None:
    """Synchronous transcript fetch — runs in executor."""
    from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
        return " ".join(seg["text"] for seg in transcript)
    except (NoTranscriptFound, TranscriptsDisabled):
        return None
    except Exception:
        return None


class YouTubeSource(BaseSource):
    def __init__(self, cfg: YouTubeSourceConfig):
        self._cfg = cfg

    async def fetch(self) -> list[RawItem]:
        cfg = self._cfg
        video_ids = list(cfg.video_ids)

        # Fetch video IDs from channels
        for ch_id in cfg.channel_ids:
            try:
                ids = await _channel_video_ids(ch_id, cfg.channel_limit)
                video_ids.extend(ids)
            except Exception:
                pass

        loop = asyncio.get_event_loop()
        items: list[RawItem] = []
        for vid in video_ids:
            text = await loop.run_in_executor(None, _get_transcript, vid, cfg.languages)
            if text:
                items.append(RawItem(
                    content=text,
                    source_url=f"https://www.youtube.com/watch?v={vid}",
                    source_type="youtube",
                    metadata={"video_id": vid},
                ))
        return items
