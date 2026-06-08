import json
from unittest.mock import patch, MagicMock
from lib.connectors.youtube import YouTubeConnector


def _proc(lines):
    r = MagicMock()
    r.stdout = "\n".join(json.dumps(x) for x in lines)
    return r


def test_youtube_missing_binary_returns_empty():
    with patch("lib.connectors.youtube.shutil.which", return_value=None):
        assert YouTubeConnector().fetch("x") == []


def test_youtube_parses_videos():
    videos = [{
        "id": "vid1", "title": "Great talk", "description": "about things",
        "channel": "Chan", "upload_date": "20260601",
        "view_count": 1000, "like_count": 50, "comment_count": 9, "duration": 120,
    }]
    with patch("lib.connectors.youtube.shutil.which", return_value="/usr/bin/yt-dlp"), \
         patch("lib.connectors.youtube.subprocess.run", return_value=_proc(videos)):
        posts = YouTubeConnector().fetch("talk", limit=5)
    assert len(posts) == 1
    p = posts[0]
    assert p.source == "youtube" and p.reactions == 50 and p.raw["views"] == 1000
    assert p.author == "Chan"
    assert p.url == "https://www.youtube.com/watch?v=vid1"
    assert "Great talk" in p.text


def test_youtube_skips_blank_and_bad_lines():
    with patch("lib.connectors.youtube.shutil.which", return_value="/usr/bin/yt-dlp"):
        r = MagicMock()
        r.stdout = "\n  \nnot-json\n" + json.dumps({"id": "v", "title": ""})
        with patch("lib.connectors.youtube.subprocess.run", return_value=r):
            assert YouTubeConnector().fetch("x") == []
