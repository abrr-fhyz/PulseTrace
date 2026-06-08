"""BeautifulSoup HTML cleaning for connector content.

Connectors (Reddit/HN RSS, scraped pages) hand back raw HTML fragments. This
turns them into clean text with block hierarchy preserved, dropping scripts,
styles, navigation chrome, and ad markup. Uses the stdlib `html.parser`
backend so no lxml dependency is required; malformed input is parsed
best-effort and never raises.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

_DROP_TAGS = (
    "script", "style", "noscript", "template",
    "nav", "footer", "aside", "form", "iframe", "svg",
)

_BLOCK_TAGS = (
    "p", "div", "section", "article", "li", "br",
    "h1", "h2", "h3", "h4", "h5", "h6", "tr",
)

_AD_PATTERN = re.compile(
    r"\b(ad|ads|advert|advertisement|banner|sponsor(ed)?|promo|"
    r"cookie|popup|newsletter|social-share|share-bar)\b",
    re.IGNORECASE,
)

_BLOCK_SEP = "\x00"
_WS = re.compile(r"\s+")


def _looks_like_ad(token_source: object) -> bool:
    if not token_source:
        return False
    if isinstance(token_source, (list, tuple)):
        joined = " ".join(token_source)
    else:
        joined = str(token_source)
    return bool(_AD_PATTERN.search(joined.replace("_", "-")))


def _soup(html: str | None) -> BeautifulSoup:
    return BeautifulSoup(html or "", "html.parser")


def _prune(soup: BeautifulSoup) -> None:
    for tag in soup(list(_DROP_TAGS)):
        tag.decompose()
    for tag in soup.find_all(True):
        if _looks_like_ad(tag.get("class")) or _looks_like_ad(tag.get("id")):
            tag.decompose()


def _normalize(text: str) -> str:
    segments = text.split(_BLOCK_SEP)
    lines = [_WS.sub(" ", seg).strip() for seg in segments]
    return "\n".join(line for line in lines if line)


def clean_html(html: str | None) -> str:
    """Return clean text from an HTML fragment, hierarchy preserved as lines."""
    if not html:
        return ""
    soup = _soup(html)
    _prune(soup)
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before(_BLOCK_SEP)
        tag.insert_after(_BLOCK_SEP)
    return _normalize(soup.get_text())


def extract_structured(html: str | None) -> dict:
    """Return {title, headings, paragraphs, text} from an HTML document."""
    if not html:
        return {"title": "", "headings": [], "paragraphs": [], "text": ""}
    soup = _soup(html)
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""
    _prune(soup)
    headings = [
        h.get_text(" ", strip=True)
        for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
        if h.get_text(strip=True)
    ]
    paragraphs = [
        p.get_text(" ", strip=True)
        for p in soup.find_all("p")
        if p.get_text(strip=True)
    ]
    return {
        "title": title,
        "headings": headings,
        "paragraphs": paragraphs,
        "text": clean_html(html),
    }
