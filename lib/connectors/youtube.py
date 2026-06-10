"""YouTube connector via yt-dlp (no API key).

Shells out to `yt-dlp "ytsearchN:query" --dump-json --no-download`, which
returns one JSON object per video with full metadata. Text = title plus
description excerpt; the agent's downstream embed/cluster handles relevance.
Requires the `yt-dlp` binary on PATH. Returns [] if it is missing or fails so
the agent loop tolerates absence.
"""
from __future__ import annotations
import json
import shutil
import subprocess

from .base import Connector, Post


def _yyyymmdd_to_epoch(value: str) -> int:
    if not value or len(value) != 8:
        return 0
    try:
        from datetime import datetime, timezone
        return int(datetime(int(value[:4]), int(value[4:6]), int(value[6:8]),
                            tzinfo=timezone.utc).timestamp())
    except (ValueError, TypeError):
        return 0


def _parse_line(line: str) -> Post | None:
    try:
        v = json.loads(line)
    except json.JSONDecodeError:
        return None
    vid = v.get("id", "")
    title = (v.get("title") or "").strip()
    desc = str(v.get("description") or "")[:500].strip()
    text = (title + ("\n\n" + desc if desc else "")).strip()
    if not text:
        return None
    return Post(
        id=f"youtube:{vid}",
        source="youtube",
        text=text[:2000],
        author=v.get("channel") or v.get("uploader") or None,
        url=f"https://www.youtube.com/watch?v={vid}",
        ts=_yyyymmdd_to_epoch(v.get("upload_date", "")),
        reactions=int(v.get("like_count") or 0),
        comments=int(v.get("comment_count") or 0),
        shares=0,
        raw={"views": int(v.get("view_count") or 0),
             "duration": v.get("duration")},
    )


class YouTubeConnector(Connector):
    name = "youtube"

    def fetch(self, query: str, limit: int = 20) -> list[Post]:
        if shutil.which("yt-dlp") is None:
            return []
        cmd = [
            "yt-dlp", "--ignore-config", "--no-cookies-from-browser",
            f"ytsearch{limit}:{query}",
            # --flat-playlist returns search entries (title/desc/channel/views)
            # without a deep per-video extraction. Full --dump-json visited each
            # of N videos (~2-3s each) — ~40s/query. Flat is ~10x faster; we lose
            # exact upload_date/like/comment counts (→0), which don't drive
            # clustering or sentiment.
            "--flat-playlist",
            "--dump-json", "--no-warnings", "--no-download",
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (subprocess.SubprocessError, OSError):
            return []
        out: list[Post] = []
        for line in res.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            post = _parse_line(line)
            if post is not None:
                out.append(post)
        return out[:limit]
