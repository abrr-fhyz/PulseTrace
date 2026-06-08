from unittest.mock import patch, MagicMock
from lib.connectors.github import GitHubConnector


def _resp(payload):
    r = MagicMock()
    r.json.return_value = payload
    r.raise_for_status = lambda: None
    return r


def test_github_parses_issue():
    payload = {"items": [{
        "id": 99, "title": "Bug in parser", "body": "It crashes",
        "html_url": "https://github.com/owner/repo/issues/7",
        "created_at": "2026-06-01T00:00:00Z", "comments": 3,
        "reactions": {"total_count": 11},
        "user": {"login": "alice"}, "state": "open",
    }]}
    with patch("lib.connectors.github.requests.get", return_value=_resp(payload)):
        posts = GitHubConnector().fetch("parser", limit=5)
    assert len(posts) == 1
    p = posts[0]
    assert p.source == "github" and p.reactions == 11 and p.comments == 3
    assert p.author == "alice" and p.raw["repo"] == "owner/repo"
    assert "Bug in parser" in p.text


def test_github_skips_empty():
    payload = {"items": [{"id": 1, "title": "", "body": "",
                          "html_url": "https://github.com/a/b/issues/1"}]}
    with patch("lib.connectors.github.requests.get", return_value=_resp(payload)):
        assert GitHubConnector().fetch("x") == []


def test_github_network_error_returns_empty():
    import requests
    with patch("lib.connectors.github.requests.get",
               side_effect=requests.RequestException("boom")):
        assert GitHubConnector().fetch("x") == []
