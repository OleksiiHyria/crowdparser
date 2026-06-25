"""LLM-based extractor: raw text → list of Candidates."""
from __future__ import annotations
import json
import os
from tenacity import retry, stop_after_attempt, wait_exponential

from crowdparser.models import RawItem, Candidate
from crowdparser.config import ExtractorConfig

_SYSTEM = """You are a structured data extractor.
Your task: given a raw text from a source, extract candidate items as instructed.
Return ONLY a JSON array. Each element must have:
  - "text": the extracted item text (verbatim or lightly cleaned)
  - "context_quote": 1-2 sentences of surrounding context proving this item is real
  - "confidence": float 0..1 (how sure you are this is a genuine item)
  - "tags": array of string tags (e.g. "tricky", "frequent", "official")
  - "metadata": object with any project-specific fields mentioned in the prompt
Return [] if nothing relevant found. No markdown, no explanation — pure JSON array."""


def _call_claude(model: str, system: str, user: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text


def _call_gemini(model: str, system: str, user: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
    m = genai.GenerativeModel(model, system_instruction=system)
    r = m.generate_content(user)
    return r.text


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
def _llm_call(model: str, system: str, user: str) -> str:
    if "gemini" in model:
        return _call_gemini(model, system, user)
    return _call_claude(model, system, user)


class LLMExtractor:
    def __init__(self, cfg: ExtractorConfig):
        self._cfg = cfg

    def extract(self, item: RawItem) -> list[Candidate]:
        cfg = self._cfg
        user_prompt = (
            f"SOURCE TYPE: {item.source_type}\n"
            f"SOURCE URL: {item.source_url}\n\n"
            f"EXTRACTION INSTRUCTIONS:\n{cfg.prompt}\n\n"
            f"RAW TEXT (truncated to 8000 chars):\n{item.content[:8000]}"
        )
        try:
            raw = _llm_call(cfg.model, _SYSTEM, user_prompt)
        except Exception:
            return []

        # Strip markdown code fences if model added them
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []

        candidates = []
        for entry in parsed[:cfg.max_candidates_per_item]:
            conf = float(entry.get("confidence", 1.0))
            if conf < cfg.min_confidence:
                continue
            candidates.append(Candidate(
                text=entry.get("text", ""),
                context_quote=entry.get("context_quote", ""),
                source_url=item.source_url,
                source_type=item.source_type,
                confidence=conf,
                tags=entry.get("tags", []),
                metadata={**item.metadata, **entry.get("metadata", {})},
            ))
        return candidates
