from __future__ import annotations
import asyncio
import os
from crowdparser.models import RawItem
from crowdparser.sources.base import BaseSource
from crowdparser.config import RedditSourceConfig


def _fetch_reddit_sync(cfg: RedditSourceConfig) -> list[RawItem]:
    import praw
    reddit = praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=os.environ.get("REDDIT_USER_AGENT", "crowdparser/0.1"),
        check_for_async=False,
    )

    items: list[RawItem] = []

    def _add(submission):
        text = f"{submission.title}\n\n{submission.selftext}".strip()
        if len(text) < 30:
            return
        items.append(RawItem(
            content=text,
            source_url=f"https://reddit.com{submission.permalink}",
            source_type="reddit",
            metadata={
                "subreddit": str(submission.subreddit),
                "post_id": submission.id,
                "score": submission.score,
                "num_comments": submission.num_comments,
            },
        ))
        # Top-level comments
        submission.comments.replace_more(limit=0)
        for comment in submission.comments.list()[:20]:
            body = comment.body or ""
            if len(body) < 30:
                continue
            items.append(RawItem(
                content=body,
                source_url=f"https://reddit.com{submission.permalink}{comment.id}",
                source_type="reddit",
                metadata={
                    "subreddit": str(submission.subreddit),
                    "post_id": submission.id,
                    "comment_id": comment.id,
                    "score": comment.score,
                },
            ))

    for sub_name in cfg.subreddits:
        sub = reddit.subreddit(sub_name)
        for post in sub.new(limit=cfg.limit):
            _add(post)

    for query in cfg.search_queries:
        for post in reddit.subreddit("all").search(query, limit=cfg.limit):
            _add(post)

    return items


class RedditSource(BaseSource):
    def __init__(self, cfg: RedditSourceConfig):
        self._cfg = cfg

    async def fetch(self) -> list[RawItem]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch_reddit_sync, self._cfg)
