from __future__ import annotations
import json
import os
from crowdparser.models import Candidate
from crowdparser.config import OutputConfig


def _apply_field_map(candidate: Candidate, field_map: dict[str, str]) -> dict:
    """Map Candidate fields to project-specific output schema."""
    base = {
        "text":          candidate.text,
        "context_quote": candidate.context_quote,
        "source_url":    candidate.source_url,
        "source_type":   candidate.source_type,
        "confidence":    candidate.confidence,
        "tags":          candidate.tags,
        **candidate.metadata,
        **{f"translation_{lang}": t for lang, t in candidate.translations.items()},
    }
    if not field_map:
        return base
    result = {}
    for src_key, dst_key in field_map.items():
        # Support dot-notation: "metadata.city" → base["city"]
        val = base
        for part in src_key.split("."):
            val = val.get(part, "") if isinstance(val, dict) else ""
        result[dst_key] = val
    return result


class JsonFileOutput:
    def __init__(self, cfg: OutputConfig, field_map: dict[str, str] = {}):
        self._cfg = cfg
        self._field_map = field_map

    def write(self, candidates: list[Candidate]):
        path = self._cfg.path
        existing = []
        if self._cfg.append and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                existing = json.load(f)

        new_rows = [_apply_field_map(c, self._field_map) for c in candidates]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing + new_rows, f, ensure_ascii=False, indent=2)
