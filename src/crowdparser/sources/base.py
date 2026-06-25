from __future__ import annotations
from abc import ABC, abstractmethod
from crowdparser.models import RawItem


class BaseSource(ABC):
    """Fetches raw content from one type of source."""

    @abstractmethod
    async def fetch(self) -> list[RawItem]:
        """Return all raw items from this source."""
        ...
