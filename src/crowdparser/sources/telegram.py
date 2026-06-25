from __future__ import annotations
import os
import re
from crowdparser.models import RawItem
from crowdparser.sources.base import BaseSource
from crowdparser.config import TelegramSourceConfig


# ── Metadata helpers ──────────────────────────────────────────────────────────

def _extract_metadata(msg, fetch_metadata: bool) -> dict:
    """Pull rich metadata from a Telethon message object."""
    meta: dict = {
        "message_id": msg.id,
        "date": str(msg.date),
        "has_media": msg.media is not None,
        "is_reply": bool(getattr(msg, "reply_to_msg_id", None)),
        "reply_to_id": getattr(msg, "reply_to_msg_id", None),
    }
    if not fetch_metadata:
        return meta

    meta["views"] = getattr(msg, "views", None)
    meta["forwards"] = getattr(msg, "forwards", None)

    # Reactions (sum of all emoji counts)
    reactions = getattr(msg, "reactions", None)
    if reactions and hasattr(reactions, "results"):
        try:
            meta["reactions"] = sum(r.count for r in reactions.results)
        except Exception:
            pass

    # Forwarded from
    fwd = getattr(msg, "fwd_from", None)
    if fwd:
        meta["forwarded_from"] = (
            getattr(fwd, "from_name", None)
            or str(getattr(fwd, "from_id", ""))
            or None
        )

    return meta


def _msg_text(msg, include_media_captions: bool) -> str:
    """Return the best available text from a message (text or media caption)."""
    text = msg.text or ""
    if not text and include_media_captions and msg.media:
        # For photos/videos/docs, the caption lives in msg.message
        text = getattr(msg, "message", "") or ""
    return text.strip()


def _channel_url(channel: str) -> str:
    handle = channel.lstrip("@")
    # Numeric channel IDs can't be used in t.me links directly
    if handle.lstrip("-").isdigit():
        return f"https://t.me/c/{handle.lstrip('-')}"
    return f"https://t.me/{handle}"


def _to_item(
    msg,
    channel: str,
    base_url: str,
    cfg: TelegramSourceConfig,
    **extra_meta,
) -> RawItem | None:
    """Convert a Telethon message to RawItem, or None if it should be skipped."""
    text = _msg_text(msg, cfg.include_media_captions)
    if len(text) < cfg.min_length:
        return None

    views = getattr(msg, "views", None)
    if cfg.min_views and views is not None and views < cfg.min_views:
        return None

    meta = {
        "channel": channel,
        **_extract_metadata(msg, cfg.fetch_metadata),
        **extra_meta,
    }
    return RawItem(
        content=text,
        source_url=f"{base_url}/{msg.id}",
        source_type="telegram",
        metadata=meta,
    )


# ── Channel discovery ─────────────────────────────────────────────────────────

async def _discover_channels(client, query: str, limit: int) -> list[str]:
    """Search Telegram globally for channels/groups matching a keyword."""
    try:
        from telethon.tl.functions.contacts import SearchRequest  # type: ignore
        result = await client(SearchRequest(q=query, limit=min(limit * 5, 50)))
        channels = []
        for chat in result.chats:
            if hasattr(chat, "username") and chat.username:
                channels.append(chat.username)
            if len(channels) >= limit:
                break
        return channels
    except Exception:
        return []


# ── Per-channel fetch ─────────────────────────────────────────────────────────

async def _fetch_channel(
    client,
    channel: str,
    cfg: TelegramSourceConfig,
) -> list[RawItem]:
    """Fetch messages (+ optional search + optional replies) from one channel."""
    items: list[RawItem] = []
    seen_ids: set[int] = set()

    try:
        entity = await client.get_entity(channel)
    except Exception:
        return []

    base_url = _channel_url(channel)

    async def _collect(iterator, **extra_meta) -> None:
        async for msg in iterator:
            if msg.id in seen_ids:
                continue
            seen_ids.add(msg.id)
            item = _to_item(msg, channel, base_url, cfg, **extra_meta)
            if item:
                items.append(item)
                # Fetch replies if requested
                if cfg.fetch_replies:
                    reply_items = await _fetch_replies(
                        client, entity, msg.id, cfg, base_url, channel
                    )
                    items.extend(reply_items)

    # 1. Regular timeline messages
    await _collect(client.iter_messages(entity, limit=cfg.limit))

    # 2. Keyword search within this channel
    for query in cfg.search_queries:
        await _collect(
            client.iter_messages(entity, search=query, limit=cfg.search_limit),
            search_query=query,
        )

    return items


async def _fetch_replies(
    client,
    entity,
    msg_id: int,
    cfg: TelegramSourceConfig,
    base_url: str,
    channel: str,
) -> list[RawItem]:
    """Fetch replies (thread) for a given message."""
    items = []
    try:
        async for reply in client.iter_messages(
            entity, reply_to=msg_id, limit=cfg.reply_limit
        ):
            item = _to_item(reply, channel, base_url, cfg, reply_to_id=msg_id)
            if item:
                items.append(item)
    except Exception:
        pass
    return items


# ── Source ────────────────────────────────────────────────────────────────────

class TelegramSource(BaseSource):
    """Fetches messages from public Telegram channels via Telethon."""

    def __init__(self, cfg: TelegramSourceConfig):
        self._cfg = cfg
        self._api_id   = int(os.environ["TELEGRAM_API_ID"])
        self._api_hash = os.environ["TELEGRAM_API_HASH"]

    async def fetch(self) -> list[RawItem]:
        from telethon import TelegramClient  # type: ignore
        from telethon.sessions import StringSession  # type: ignore

        cfg = self._cfg
        session_str = os.environ.get("TELEGRAM_SESSION", "")
        client = TelegramClient(
            StringSession(session_str) if session_str else "crowdparser_session",
            self._api_id,
            self._api_hash,
            flood_sleep_threshold=60,  # auto-sleep on FloodWaitError up to 60s
        )
        await client.start()

        all_channels = list(cfg.channels)

        # Channel discovery
        for query in cfg.discover_channels:
            found = await _discover_channels(client, query, cfg.discover_limit)
            for ch in found:
                if ch not in all_channels:
                    all_channels.append(ch)

        items: list[RawItem] = []
        for channel in all_channels:
            channel_items = await _fetch_channel(client, channel, cfg)
            items.extend(channel_items)

        await client.disconnect()
        return items
