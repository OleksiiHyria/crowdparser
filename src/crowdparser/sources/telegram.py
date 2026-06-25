from __future__ import annotations
import os
from crowdparser.models import RawItem
from crowdparser.sources.base import BaseSource
from crowdparser.config import TelegramSourceConfig


class TelegramSource(BaseSource):
    """Fetches messages from public Telegram channels via Telethon."""

    def __init__(self, cfg: TelegramSourceConfig):
        self._cfg = cfg
        self._api_id   = int(os.environ["TELEGRAM_API_ID"])
        self._api_hash = os.environ["TELEGRAM_API_HASH"]

    async def fetch(self) -> list[RawItem]:
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        session_str = os.environ.get("TELEGRAM_SESSION", "")
        client = TelegramClient(
            StringSession(session_str) if session_str else "crowdparser_session",
            self._api_id,
            self._api_hash,
        )
        await client.start()

        items: list[RawItem] = []
        for channel in self._cfg.channels:
            try:
                entity = await client.get_entity(channel)
                channel_url = f"https://t.me/{channel.lstrip('@')}"
                async for msg in client.iter_messages(entity, limit=self._cfg.limit):
                    text = msg.text or ""
                    if len(text) < 30:
                        continue
                    items.append(RawItem(
                        content=text,
                        source_url=f"{channel_url}/{msg.id}",
                        source_type="telegram",
                        metadata={
                            "channel": channel,
                            "message_id": msg.id,
                            "date": str(msg.date),
                        },
                    ))
            except Exception:
                pass

        await client.disconnect()
        return items
