"""YAML-driven pipeline config — everything project-specific lives here."""
from __future__ import annotations
from typing import Any, Literal, Union
from pydantic import BaseModel, Field
import yaml


class YouTubeSourceConfig(BaseModel):
    type: Literal["youtube"] = "youtube"
    video_ids: list[str] = []
    channel_ids: list[str] = []       # fetch N latest videos from channel
    channel_limit: int = 10           # videos per channel
    search_queries: list[str] = []    # keyword search → video IDs
    search_limit: int = 20            # max videos per search query
    search_lang: str = "pl"           # relevanceLanguage for Data API
    languages: list[str] = ["pl", "uk", "ru", "en"]
    fetch_metadata: bool = True       # title + description + channel
    description_fallback: bool = True # use description if no transcript
    fetch_comments: bool = False      # top comments as separate RawItems
    comments_limit: int = 50          # max comments per video


class TelegramSourceConfig(BaseModel):
    type: Literal["telegram"] = "telegram"
    channels: list[str] = []          # @channel_handle or channel_id
    limit: int = 200                  # messages per channel
    # Credentials passed via env: TELEGRAM_API_ID, TELEGRAM_API_HASH


class RedditSourceConfig(BaseModel):
    type: Literal["reddit"] = "reddit"
    subreddits: list[str] = []
    search_queries: list[str] = []
    limit: int = 100
    # Credentials via env: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT


class WebSourceConfig(BaseModel):
    type: Literal["web"] = "web"
    urls: list[str] = []
    use_jina: bool = True              # fallback to Jina Reader on errors

    # Pagination
    follow_pagination: bool = False    # follow "next page" links
    max_pages: int = 5                 # max pages per start URL

    # Rate limiting
    rate_limit_delay: float = 1.0     # seconds between requests
    respect_robots: bool = True        # honour robots.txt

    # Thread / forum structure
    extract_thread_structure: bool = False  # split posts into separate RawItems
    post_selector: str = ""            # CSS selector for individual post elements
    next_page_selector: str = ""       # CSS selector for next-page link

    # Sitemap discovery
    sitemap_url: str = ""              # parse sitemap.xml → add URLs to queue
    sitemap_filter: str = ""           # keep only URLs containing this substring
    sitemap_limit: int = 100           # max URLs from sitemap


SourceConfig = Union[YouTubeSourceConfig, TelegramSourceConfig, RedditSourceConfig, WebSourceConfig]


class ExtractorConfig(BaseModel):
    model: str = "claude-sonnet-4-6"  # or gemini-2.0-flash
    prompt: str                        # project-specific extraction prompt
    max_candidates_per_item: int = 5
    min_confidence: float = 0.6


class OutputConfig(BaseModel):
    type: Literal["json", "postgres", "webhook"] = "json"
    # json
    path: str = "candidates.json"
    append: bool = True               # append to existing file
    # postgres
    dsn: str = ""
    table: str = "candidates"
    # webhook
    url: str = ""
    headers: dict[str, str] = {}


class DeduplicationConfig(BaseModel):
    enabled: bool = True
    store: Literal["memory", "json", "postgres"] = "json"
    store_path: str = ".seen_hashes.json"


class PipelineConfig(BaseModel):
    name: str
    description: str = ""
    sources: list[Any] = []           # list of SourceConfig variants
    extractor: ExtractorConfig
    output: OutputConfig = Field(default_factory=OutputConfig)
    dedup: DeduplicationConfig = Field(default_factory=DeduplicationConfig)
    # Field mapping: how Candidate fields map to project output schema
    field_map: dict[str, str] = {}
    # e.g. {"text": "question_text", "metadata.suspected_city": "suspected_city"}

    @classmethod
    def from_yaml(cls, path: str) -> "PipelineConfig":
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        # Resolve typed source configs
        resolved_sources = []
        for s in data.get("sources", []):
            t = s.get("type")
            model = {
                "youtube":  YouTubeSourceConfig,
                "telegram": TelegramSourceConfig,
                "reddit":   RedditSourceConfig,
                "web":      WebSourceConfig,
            }.get(t)
            if model:
                resolved_sources.append(model(**{k: v for k, v in s.items() if k != "type"}, type=t))
        data["sources"] = resolved_sources
        return cls(**data)
