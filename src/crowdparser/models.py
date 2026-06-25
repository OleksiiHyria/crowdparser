"""Core data models — project-agnostic."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RawItem:
    """Raw content unit fetched from a source."""
    content: str
    source_url: str
    source_type: str          # youtube | telegram | reddit | web
    metadata: dict[str, Any] = field(default_factory=dict)
    # e.g. video_id, channel, subreddit, post_id, thread_url


@dataclass
class Candidate:
    """Extracted candidate — ready for moderation queue."""
    text: str                  # the extracted question/item text
    context_quote: str         # surrounding context proving it's real
    source_url: str
    source_type: str
    confidence: float = 1.0    # 0..1, set by extractor
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    # project-specific fields go into metadata (suspected_city, voivodeship, etc.)
    # enrichers add translations, classifications, etc.
    translations: dict[str, str] = field(default_factory=dict)
    # {"uk": "...", "ru": "...", "en": "..."}
