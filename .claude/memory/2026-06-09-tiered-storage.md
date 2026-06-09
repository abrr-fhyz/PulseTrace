# Tiered Storage Layer (`db/`) — Postgres+pgvector + MongoDB

> Added 2026-06-09 on branch `feat/db` (PR → `shyan`). Closes the biggest gap
> from `.claude/submission-gap-audit.md` (Q4 storage: claimed Supabase/pgvector/
> MongoDB, previously absent — was file-based JSON + FAISS only).

## Stance: additive + graceful fallback
File storage (`data/runs/<id>/` + FAISS) stays the source of truth. The DB
clients activate **only** when their env vars are present; otherwise
`.enabled is False` and the pipeline runs unchanged. A cold checkout/demo with
no creds behaves exactly as before. DB writes are best-effort: a DB outage
logs a warning and never raises into the run (`lib/store.py:_mirror_to_db`).

## Files
- `db/models.py` — Pydantic `RunRecord` / `PostRecord` (+ `from_raw()` mapping
  pipeline post dicts; engagement fallback `r + 2c + 3s`; ts→crawl_date).
- `db/supabase_client.py` — psycopg2 `ThreadedConnectionPool`; on-demand
  composite partitions; batched `halfvec` inserts; methods: `upsert_run`,
  `insert_posts`, `insert_clusters`, `upsert_artifact`, `top_posts_by_engagement`,
  `vector_search` (pgvector cosine, topic-scoped — replaces FAISS), `get_clusters`,
  `get_artifact`, `apply_schema`, `health`.
- `db/mongo_client.py` — hot/cold tiering (`posts_hot`/`posts_cold`/`sessions`);
  TTL backstop; `write_session`, `get_session`, `top_posts`, `archive_aged`
  (compacts hot→cold). Pool tuned for long-running OLTP Flask server.
- `db/schema.sql` — `vector` ext; `runs`; `posts` partitioned
  `RANGE(crawl_date) → LIST(topic_id)` with DEFAULT leaves; `clusters`
  (centroid `halfvec`); `run_artifacts` (jsonb); B-Tree on `engagement_score`,
  HNSW on every `halfvec`; `ensure_posts_partition()` plpgsql; RLS on all.
- `db/__init__.py` — `get_supabase()` / `get_mongo()` singletons; self-loads `.env`.
- `lib/store.py` — `_mirror_to_db` fan-out of all 6 artifacts (run/posts/clusters
  → structured tables; evidence/ranked/orchestration_summary → `run_artifacts`).

## Key constraint
Gemini embeddings = **3072 dims** > pgvector's 2000 ANN limit, so embeddings use
`halfvec(3072)` + HNSW cosine (NOT plain `vector`). Change `PULSE_EMBED_DIM` +
the `halfvec(N)` declarations together if the embedder changes.

## Config — everything via `.env` (see `.env.example`)
`DATABASE_URL` / `SUPABASE_DB_URL`, `SUPABASE_URL`, `PULSE_EMBED_DIM`,
`PG_POOL_MIN`/`PG_POOL_MAX`; `MONGODB_URI`, `MONGODB_DB`,
`MONGODB_MAX_POOL`/`MONGODB_MIN_POOL`, `PULSE_HOT_TTL_DAYS`,
`PULSE_ARCHIVE_AGE_DAYS`.

## Live provisioning status (2026-06-09)
- **Supabase: DONE + verified.** Project `pulsetrace` (ref `gifzlqrnvbrwtjzqucov`,
  ap-south-1, PG17 + pgvector 0.8.0). Schema applied via MCP `execute_sql`.
  Verified live: engagement leaderboard order, halfvec HNSW cosine (exact=1.0,
  ranked), composite partitions incl. on-demand topic leaf, cluster + jsonb
  artifact round-trip. Security advisors: **0 errors** (child-partition RLS gap +
  function `search_path` fixed). `vector` kept in `public` (intentional — moving
  breaks unqualified `halfvec` casts).
- **Runtime routing:** direct `db.<ref>.supabase.co:5432` is IPv6-only and
  unreachable from an IPv4 box — use the **Supavisor pooler** `:6543`.
- **MongoDB: blocked (environmental).** Cluster wired + code verified, but the
  dev network's ISP applies DPI to TCP 27017 (TLS ClientHello reset, alert 80) —
  needs a VPN/hotspot to reach Atlas. Not a code issue.
