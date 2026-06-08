from __future__ import annotations

from lib.ingest.html_clean import clean_html, extract_structured


def test_strips_script_and_style():
    html = "<p>keep</p><script>evil()</script><style>.x{}</style>"
    out = clean_html(html)
    assert "keep" in out
    assert "evil" not in out
    assert ".x" not in out


def test_removes_nav_footer_aside():
    html = "<nav>menu</nav><article>body text</article><footer>copyright</footer>"
    out = clean_html(html)
    assert "body text" in out
    assert "menu" not in out
    assert "copyright" not in out


def test_removes_ad_by_class_and_id():
    html = (
        '<div class="ad-banner">buy now</div>'
        '<div id="advertisement">sponsored</div>'
        "<p>real content</p>"
    )
    out = clean_html(html)
    assert "real content" in out
    assert "buy now" not in out
    assert "sponsored" not in out


def test_preserves_block_hierarchy_with_newlines():
    html = "<h1>Title</h1><p>Para one.</p><p>Para two.</p>"
    out = clean_html(html)
    lines = [l for l in out.splitlines() if l.strip()]
    assert lines == ["Title", "Para one.", "Para two."]


def test_collapses_inline_whitespace():
    html = "<p>too    many\n\tspaces</p>"
    assert clean_html(html) == "too many spaces"


def test_malformed_html_does_not_raise():
    html = "<p>unclosed <b>bold <div>nested</p> stray"
    out = clean_html(html)
    assert "unclosed" in out
    assert "bold" in out


def test_empty_and_none_return_empty():
    assert clean_html("") == ""
    assert clean_html(None) == ""


def test_plain_text_passthrough():
    assert clean_html("just text") == "just text"


def test_extract_structured_returns_title_headings_paragraphs():
    html = (
        "<html><head><title>Doc</title></head><body>"
        "<h1>Heading A</h1><p>First para.</p>"
        "<script>x</script><h2>Heading B</h2><p>Second para.</p>"
        "</body></html>"
    )
    s = extract_structured(html)
    assert s["title"] == "Doc"
    assert s["headings"] == ["Heading A", "Heading B"]
    assert s["paragraphs"] == ["First para.", "Second para."]
    assert "First para." in s["text"]
    assert "x" not in s["text"]


def test_extract_structured_empty():
    s = extract_structured("")
    assert s["title"] == ""
    assert s["headings"] == []
    assert s["paragraphs"] == []
    assert s["text"] == ""
