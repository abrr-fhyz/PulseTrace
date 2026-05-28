"""Reddit connector via PRAW. Read-only application auth."""
from __future__ import annotations
import os
import time
from .base import Connector, Post


class RedditConnector(Connector):
    name = "reddit"

    def __init__(self) -> None:
        import praw
        self._praw = praw.Reddit(
            client_id=os.environ["REDDIT_CLIENT_ID"],
            client_secret=os.environ["REDDIT_CLIENT_SECRET"],
            user_agent=os.environ.get("REDDIT_USER_AGENT", "pulsetrace/0.2"),
        )
        self._praw.read_only = True

    def fetch(self, query: str, limit: int = 50) -> list[Post]:
        out: list[Post] = []
        for sub in self._praw.subreddit("all").search(query, limit=limit, sort="relevance"):
            text = (getattr(sub, "title", "") + "\n\n" + (getattr(sub, "selftext", "") or "")).strip()
            if not text:
                continue
            out.append(Post(
                id=f"reddit:{sub.id}",
                source="reddit",
                text=text,
                author=str(sub.author) if sub.author else None,
                url=f"https://reddit.com{sub.permalink}",
                ts=int(getattr(sub, "created_utc", 0) or time.time()),
                reactions=int(getattr(sub, "score", 0) or 0),
                comments=int(getattr(sub, "num_comments", 0) or 0),
                shares=0,
                raw={"subreddit": str(sub.subreddit)},
            ))
        return out
