from lib.connectors.instagram import _normalize_tag, InstagramConnector


def test_normalize_tag_strips_non_alnum():
    assert _normalize_tag("hello world!") == "helloworld"
    assert _normalize_tag("#foo-bar_baz 123") == "foobarbaz123"


def test_normalize_tag_empty_falls_back():
    assert _normalize_tag("!!!") == "trending"


def test_fetch_returns_list():
    # Without creds + without instaloader installed or network, must return [].
    out = InstagramConnector().fetch("xyz")
    assert isinstance(out, list)
