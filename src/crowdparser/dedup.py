"""Content-hash deduplication — prevents re-processing the same items across runs."""
from __future__ import annotations
import hashlib
import json
import os
from crowdparser.models import Candidate
from crowdparser.config import DeduplicationConfig


def _hash(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode()).hexdigest()[:16]


class Deduplicator:
    def __init__(self, cfg: DeduplicationConfig):
        self._cfg = cfg
        self._seen: set[str] = set()
        if cfg.enabled and cfg.store == "json" and os.path.exists(cfg.store_path):
            with open(cfg.store_path, encoding="utf-8") as f:
                self._seen = set(json.load(f))

    def is_new(self, candidate: Candidate) -> bool:
        if not self._cfg.enabled:
            return True
        h = _hash(candidate.text)
        if h in self._seen:
            return False
        self._seen.add(h)
        return True

    def save(self):
        if self._cfg.enabled and self._cfg.store == "json":
            with open(self._cfg.store_path, "w", encoding="utf-8") as f:
                json.dump(list(self._seen), f)
