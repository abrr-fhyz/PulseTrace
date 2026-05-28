# Decisions Log

Append-only. Newest at top. Format: date — decision — reason.

## 2026-05-29
- **Adopt `.claude/{memory,plans,rules,skills,specs}` layout.** Mirror readest-app convention. CLAUDE.md at root indexes it.
- **Branch v2 work to `shyan`.** Keep `v1.1` clean; merge later if v2 stabilizes.
- **No durable DB; per-run JSON + FAISS files.** Hackathon scope; SQLite would add ceremony without payoff.
- **`gpt-4o-mini` as default LLM** via `PULSETRACE_LLM_MODEL` env. Cheap, fast, JSON-mode reliable.
- **`text-embedding-3-small` for embeddings.** 1536-d, $0.02/1M tokens; cap at 500 posts/run.
- **HDBSCAN min_cluster_size=4.** Hackathon sample sizes are small; smaller min misses themes.
