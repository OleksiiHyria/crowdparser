from __future__ import annotations
import httpx
from crowdparser.models import Candidate
from crowdparser.config import OutputConfig
from crowdparser.output.json_file import _apply_field_map


class WebhookOutput:
    def __init__(self, cfg: OutputConfig, field_map: dict[str, str] = {}):
        self._cfg = cfg
        self._field_map = field_map

    def write(self, candidates: list[Candidate]):
        rows = [_apply_field_map(c, self._field_map) for c in candidates]
        with httpx.Client(timeout=30) as client:
            for row in rows:
                client.post(self._cfg.url, json=row, headers=self._cfg.headers)
