"""Rolling-summary memory for chat threads.

Keeps the last RECENT_TURNS user/assistant pairs verbatim; older pairs are
compressed into a running `summary` (one LLM call per compaction). The summary
plus the recent verbatim turns form the preamble prepended to a RAG question so
follow-ups stay coherent without unbounded context growth.

First real implementation of Q-token-02 (rolling summary memory), previously
audited ABSENT in .claude/specs/2026-06-09-token-optimization-audit.md.
"""
from __future__ import annotations

from .llm import chat_json

RECENT_TURNS = 6

SUMMARIZE_SYS = (
    "You maintain a running summary of a research conversation. Merge the prior "
    "summary with the older exchanges below into a single concise summary (<=120 "
    "words) that preserves the user's goals, established facts, and open threads. "
    'Output JSON: {"summary": "..."}'
)


def _complete_turns(messages: list[dict]) -> int:
    """Number of user+assistant pairs, ignoring a trailing unanswered user."""
    pairs = 0
    i = 0
    while i + 1 < len(messages):
        if messages[i].get("role") == "user" and messages[i + 1].get("role") == "assistant":
            pairs += 1
            i += 2
        else:
            i += 1
    return pairs


def _render(messages: list[dict]) -> str:
    out = []
    for m in messages:
        who = "User" if m.get("role") == "user" else "Assistant"
        out.append(f"{who}: {m.get('content', '')}")
    return "\n".join(out)


def compact(thread: dict) -> dict:
    """Fold turns beyond RECENT_TURNS into thread['summary']. Idempotent under
    the threshold. Mutates and returns the thread."""
    messages = thread.get("messages", [])
    turns = _complete_turns(messages)
    if turns <= RECENT_TURNS:
        return thread

    overflow_turns = turns - RECENT_TURNS
    cut = overflow_turns * 2
    older, recent = messages[:cut], messages[cut:]

    prior = thread.get("summary", "")
    user_blob = (f"Prior summary:\n{prior}\n\n" if prior else "") + \
        f"Older exchanges:\n{_render(older)}"
    try:
        out = chat_json(SUMMARIZE_SYS, user_blob, stage="chat_summary")
        thread["summary"] = str(out.get("summary", prior)) or prior
    except Exception:
        # Memory is best-effort: on summarizer failure keep the prior summary and
        # still drop the overflow rather than letting context grow unbounded.
        thread["summary"] = prior

    thread["messages"] = recent
    thread["archived_count"] = int(thread.get("archived_count", 0)) + overflow_turns
    return thread


def build_preamble(thread: dict) -> str:
    """Summary + recent verbatim turns, for prepending to a RAG question."""
    summary = (thread.get("summary") or "").strip()
    recent = _render(thread.get("messages", [])).strip()
    parts = []
    if summary:
        parts.append(f"Earlier conversation summary:\n{summary}")
    if recent:
        parts.append(f"Recent exchanges:\n{recent}")
    return "\n\n".join(parts)
