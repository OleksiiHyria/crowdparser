from crowdparser.sources.youtube import YouTubeSource
from crowdparser.sources.telegram import TelegramSource
from crowdparser.sources.reddit import RedditSource
from crowdparser.sources.web import WebSource
from crowdparser.config import (
    YouTubeSourceConfig, TelegramSourceConfig,
    RedditSourceConfig, WebSourceConfig,
)


def build_source(cfg):
    return {
        YouTubeSourceConfig:  YouTubeSource,
        TelegramSourceConfig: TelegramSource,
        RedditSourceConfig:   RedditSource,
        WebSourceConfig:      WebSource,
    }[type(cfg)](cfg)
