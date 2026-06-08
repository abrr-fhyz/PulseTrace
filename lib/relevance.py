"""Query-centric relevance scoring + query cleanup.

Adapted from the last30days engine. The score is deliberately query-centric:
exact phrase matches score high, generic-word-only matches stay below the
filter line, and off-topic text scores ~0. PulseTrace uses this to gate and
rank posts against the *original topic* instead of ranking on engagement alone.
"""
from __future__ import annotations
import re

STOPWORDS = frozenset({
    "the", "a", "an", "to", "for", "how", "is", "in", "of", "on", "and", "with",
    "from", "by", "at", "this", "that", "it", "my", "your", "i", "me", "we",
    "you", "what", "are", "do", "can", "its", "be", "or", "not", "no", "so",
    "if", "but", "about", "all", "just", "get", "has", "have", "was", "will",
})

SYNONYMS: dict[str, set[str]] = {
    "js": {"javascript"}, "javascript": {"js"},
    "ts": {"typescript"}, "typescript": {"ts"},
    "ai": {"artificial", "intelligence"}, "ml": {"machine", "learning"},
    "rag": {"retrieval"},
}

LOW_SIGNAL_QUERY_TOKENS = frozenset({
    "advice", "best", "chance", "chances", "code", "compare", "comparison",
    "differences", "explain", "guide", "guides", "how", "latest", "news",
    "odds", "opinion", "opinions", "prediction", "predictions", "pricing",
    "probability", "prompt", "prompting", "prompts", "rate", "review",
    "reviews", "thoughts", "tip", "tips", "tutorial", "tutorials", "update",
    "updates", "use", "using", "versus", "vs", "worth",
})

PREFIXES = [
    "what are the best", "what is the best", "what are the latest",
    "what are people saying about", "what do people think about",
    "how do i use", "how to use", "how to set up", "how to",
    "what are", "what is", "tips for", "best practices for",
]

NOISE_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "and", "or", "of", "in", "on",
    "for", "with", "about", "to", "how", "what", "which", "who", "why", "when",
    "where", "does", "should", "could", "would", "best", "top", "good", "great",
    "latest", "new", "news", "update", "updates", "trending", "hottest", "hot",
    "popular", "viral", "practices", "features", "guide", "tutorial",
    "recommendations", "advice", "review", "reviews", "comparison", "versus",
    "vs", "prompt", "prompts", "prompting", "techniques", "tips", "tricks",
    "methods", "strategies", "approaches", "using", "uses", "use", "people",
    "saying", "think", "said", "lately", "set", "up", "a",
})


def tokenize(text: str) -> set[str]:
    words = re.sub(r"[^\w\s]", " ", text.lower()).split()
    tokens = {w for w in words if w not in STOPWORDS and len(w) > 1}
    expanded = set(tokens)
    for t in tokens:
        if t in SYNONYMS:
            expanded.update(SYNONYMS[t])
    return expanded


def _normalize_phrase(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def token_overlap_relevance(query: str, text: str) -> float:
    """Relevance of `text` to `query`, in [0.0, 1.0]. 0.5 for empty query."""
    q_tokens = tokenize(query)
    if not q_tokens:
        return 0.5
    t_tokens = tokenize(text)
    overlap_tokens = q_tokens & t_tokens
    if not overlap_tokens:
        return 0.0
    overlap = len(overlap_tokens)

    informative_q = {t for t in q_tokens if t not in LOW_SIGNAL_QUERY_TOKENS} or q_tokens
    coverage = overlap / len(q_tokens)
    informative_overlap = len(informative_q & t_tokens) / len(informative_q)
    precision = overlap / (min(len(t_tokens), len(q_tokens) + 4) or 1)

    base = 0.55 * (coverage ** 1.35) + 0.25 * informative_overlap + 0.20 * precision

    # Only generic query words matched -> keep below the relevance floor.
    if informative_q and not (informative_q & t_tokens):
        return round(min(0.24, base), 2)

    phrase_bonus = 0.0
    nq = _normalize_phrase(query)
    if nq and nq in _normalize_phrase(text):
        phrase_bonus = 0.12 if len(nq.split()) > 1 else 0.16
    return round(min(1.0, base + phrase_bonus), 2)


def extract_core_subject(topic: str, max_words: int | None = None) -> str:
    """Strip question/meta prefixes and noise words to a compact search subject."""
    text = topic.lower().strip()
    if not text:
        return text
    for p in PREFIXES:
        if text.startswith(p + " "):
            text = text[len(p):].strip()
            break
    words = text.split()
    filtered = [w for w in words if w not in NOISE_WORDS]
    if max_words is not None and filtered:
        filtered = filtered[:max_words]
    result = " ".join(filtered) if filtered else text
    return result.rstrip("?!.")


def extract_compound_terms(topic: str) -> list[str]:
    """Multi-word terms worth quoting: hyphenated + TitleCase sequences."""
    terms: list[str] = []
    for m in re.finditer(r"\b\w+-\w+(?:-\w+)*\b", topic):
        terms.append(m.group())
    for m in re.finditer(r"(?:[A-Z][a-z]+\s+){1,}[A-Z][a-z]+", topic):
        terms.append(m.group())
    return terms
