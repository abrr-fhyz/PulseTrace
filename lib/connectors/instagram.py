"""Instagram connector via instaloader.

WARNING: Instagram blocks aggressively.
 - Needs a session file at `info/ig_session` OR env `IG_USERNAME` + `IG_PASSWORD`.
 - Anonymous requests are rate-limited within a few calls; login is recommended.
 - Hashtag search may return only top-public posts; captions can be empty.
 - Risk of session ban. Use a throwaway account. Never your main.
 - Returns [] on any failure so the agent loop tolerates absence.
"""
from __future__ import annotations
import os
import re
import time
from pathlib import Path

from .base import Connector, Post


SESSION_DIR = Path("info")


def _normalize_tag(query: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", query).lower()[:50] or "trending"


def _make_loader():
    try:
        import instaloader
    except ImportError:
        return None
    L = instaloader.Instaloader(
        download_pictures=False, download_videos=False,
        download_video_thumbnails=False, download_geotags=False,
        download_comments=False, save_metadata=False, post_metadata_txt_pattern="",
    )
    user = os.environ.get("IG_USERNAME")
    pw = os.environ.get("IG_PASSWORD")
    session = SESSION_DIR / f"ig_session_{user}" if user else None
    try:
        if session and session.exists() and user:
            L.load_session_from_file(user, str(session))
            return L
        if user and pw:
            L.login(user, pw)
            SESSION_DIR.mkdir(parents=True, exist_ok=True)
            L.save_session_to_file(str(SESSION_DIR / f"ig_session_{user}"))
            return L
    except Exception:
        return None
    return L  # anonymous; will likely rate-limit


def _fetch(query: str, limit: int) -> list[Post]:
    L = _make_loader()
    if L is None:
        return []
    import instaloader
    tag = _normalize_tag(query)
    out: list[Post] = []
    try:
        hashtag = instaloader.Hashtag.from_name(L.context, tag)
        for p in hashtag.get_posts():
            caption = (p.caption or "").strip()
            if not caption:
                continue
            out.append(Post(
                id=f"instagram:{p.shortcode}",
                source="instagram",
                text=caption[:2000],
                author=str(p.owner_username) if p.owner_username else None,
                url=f"https://www.instagram.com/p/{p.shortcode}/",
                ts=int(p.date_utc.timestamp()) if p.date_utc else int(time.time()),
                reactions=int(getattr(p, "likes", 0) or 0),
                comments=int(getattr(p, "comments", 0) or 0),
                shares=0,
                raw={"hashtag": tag},
            ))
            if len(out) >= limit:
                break
    except Exception:
        return out
    return out


class InstagramConnector(Connector):
    name = "instagram"

    def fetch(self, query: str, limit: int = 30) -> list[Post]:
        try:
            return _fetch(query, limit)
        except Exception:
            return []
