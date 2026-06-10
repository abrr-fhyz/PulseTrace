-- PulseTrace tiered storage — Postgres + pgvector (Supabase-compatible).
-- Idempotent: safe to run repeatedly (execute_sql / psql / Supabase MCP).
--
-- Embedding dim = 3072 (Gemini gemini-embedding-001). pgvector's `vector`
-- type cannot be ANN-indexed above 2000 dims, so embeddings use `halfvec`
-- (16-bit, indexable to 4000 dims). If you switch to a 1536/768-dim embedder,
-- change the two halfvec(3072) declarations + PULSE_EMBED_DIM together.

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------- runs
CREATE TABLE IF NOT EXISTS runs (
    run_id      text PRIMARY KEY,
    topic       text NOT NULL,
    topic_id    text NOT NULL,
    sources     text[] NOT NULL DEFAULT '{}',
    status      text NOT NULL DEFAULT 'running',
    started_at  timestamptz,
    finished_at timestamptz,
    n_posts     integer NOT NULL DEFAULT 0,
    meta        jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_runs_topic ON runs (topic_id);
CREATE INDEX IF NOT EXISTS ix_runs_started ON runs (started_at DESC);
ALTER TABLE runs ADD COLUMN IF NOT EXISTS owner_email text;
CREATE INDEX IF NOT EXISTS ix_runs_owner ON runs (owner_email);

-- ---------------------------------------------------------------- posts
-- Composite partitioning (Requirement 3): RANGE(crawl_date) parent,
-- sub-partitioned LIST(topic_id). The PK must include every partition key.
CREATE TABLE IF NOT EXISTS posts (
    id               text NOT NULL,
    run_id           text NOT NULL,
    topic_id         text NOT NULL,
    source           text NOT NULL DEFAULT '',
    text             text NOT NULL DEFAULT '',
    author           text NOT NULL DEFAULT '',
    url              text NOT NULL DEFAULT '',
    ts               timestamptz NOT NULL DEFAULT now(),
    crawl_date       date NOT NULL,
    reactions        integer NOT NULL DEFAULT 0,
    comments         integer NOT NULL DEFAULT 0,
    shares           integer NOT NULL DEFAULT 0,
    engagement_score double precision NOT NULL DEFAULT 0,
    embedding        halfvec(3072),
    PRIMARY KEY (id, topic_id, crawl_date)
) PARTITION BY RANGE (crawl_date);

-- Top-level DEFAULT so any crawl_date lands somewhere even before the monthly
-- partition is created. Itself sub-partitioned by topic for a uniform shape.
CREATE TABLE IF NOT EXISTS posts_default
    PARTITION OF posts DEFAULT
    PARTITION BY LIST (topic_id);
CREATE TABLE IF NOT EXISTS posts_default_default
    PARTITION OF posts_default DEFAULT;

-- Example pre-created month (current period). The Python client creates these
-- on demand via _ensure_partition(); this seeds one so a cold DB is queryable.
CREATE TABLE IF NOT EXISTS posts_y2026m06
    PARTITION OF posts
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01')
    PARTITION BY LIST (topic_id);
CREATE TABLE IF NOT EXISTS posts_y2026m06_default
    PARTITION OF posts_y2026m06 DEFAULT;

-- Helper so non-Python callers (psql, n8n, MCP) can mint partitions too.
-- search_path pinned (advisor 0011); enables RLS on every partition it mints
-- since child partitions do NOT inherit the parent's RLS flag (advisor 0013).
CREATE OR REPLACE FUNCTION ensure_posts_partition(p_date date, p_topic_id text)
RETURNS void LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    m_start date := date_trunc('month', p_date)::date;
    m_end   date := (date_trunc('month', p_date) + interval '1 month')::date;
    month   text := to_char(p_date, '"y"YYYY"m"MM');
    rng     text := 'posts_' || month;
    slug    text := regexp_replace(lower(p_topic_id), '[^a-z0-9]+', '_', 'g');
    leaf    text := rng || '_' || left(slug, 40);
BEGIN
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF posts '
        'FOR VALUES FROM (%L) TO (%L) PARTITION BY LIST (topic_id)',
        rng, m_start, m_end);
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I PARTITION OF %I DEFAULT',
                   rng || '_default', rng);
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I PARTITION OF %I FOR VALUES IN (%L)',
                   leaf, rng, p_topic_id);
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', rng);
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', rng || '_default');
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', leaf);
END;
$$;

-- ---------------------------------------------------------------- indexes
-- B-Tree leaderboard index (Requirement 3). Partitioned tables propagate the
-- index to every partition; topic_id is pruned by the partition itself.
CREATE INDEX IF NOT EXISTS ix_posts_engagement
    ON posts (engagement_score DESC);
CREATE INDEX IF NOT EXISTS ix_posts_topic_date
    ON posts (topic_id, crawl_date);
CREATE INDEX IF NOT EXISTS ix_posts_run
    ON posts (run_id);

-- pgvector ANN: HNSW over halfvec, cosine. Built on the parent; pgvector
-- creates a matching index per partition. m/ef tuned for ≤500 posts/run.
CREATE INDEX IF NOT EXISTS ix_posts_embedding_hnsw
    ON posts USING hnsw (embedding halfvec_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ---------------------------------------------------------------- RLS
-- `posts`/`runs` live in `public`. If the Supabase Data API exposes this
-- schema, enable RLS so rows aren't world-readable via anon/authenticated.
-- Service-role (server-side psycopg2) bypasses RLS, so the pipeline is
-- unaffected. Add SELECT policies here if you expose read access to clients.
-- Child partitions do NOT inherit the parent RLS flag and are individually
-- exposed to PostgREST (advisor 0013) — enable on every level explicitly.
ALTER TABLE runs                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE posts                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE posts_default         ENABLE ROW LEVEL SECURITY;
ALTER TABLE posts_default_default ENABLE ROW LEVEL SECURITY;
ALTER TABLE posts_y2026m06        ENABLE ROW LEVEL SECURITY;
ALTER TABLE posts_y2026m06_default ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------- clusters
-- Cluster output (clusters.json): label, sentiment split, member ids, and the
-- centroid embedding (enables cluster-level semantic search via HNSW).
CREATE TABLE IF NOT EXISTS clusters (
    run_id        text NOT NULL,
    cluster_id    integer NOT NULL,
    topic_id      text NOT NULL,
    label         text NOT NULL DEFAULT '',
    descr         text NOT NULL DEFAULT '',
    sentiment_pos double precision NOT NULL DEFAULT 0,
    sentiment_neu double precision NOT NULL DEFAULT 0,
    sentiment_neg double precision NOT NULL DEFAULT 0,
    members       text[] NOT NULL DEFAULT '{}',
    top_posts     text[] NOT NULL DEFAULT '{}',
    centroid      halfvec(3072),
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, cluster_id)
);
CREATE INDEX IF NOT EXISTS ix_clusters_topic ON clusters (topic_id);
CREATE INDEX IF NOT EXISTS ix_clusters_run ON clusters (run_id);
CREATE INDEX IF NOT EXISTS ix_clusters_centroid_hnsw
    ON clusters USING hnsw (centroid halfvec_cosine_ops) WITH (m=16, ef_construction=64);
ALTER TABLE clusters ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------- artifacts
-- Flexible jsonb store for the remaining per-run artifacts (evidence.json,
-- ranked.json, orchestration_summary.json, …) — keeps every pipeline output
-- in Postgres without rigid per-shape columns.
CREATE TABLE IF NOT EXISTS run_artifacts (
    run_id     text NOT NULL,
    name       text NOT NULL,
    topic_id   text NOT NULL DEFAULT '',
    data       jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, name)
);
CREATE INDEX IF NOT EXISTS ix_artifacts_topic ON run_artifacts (topic_id);
CREATE INDEX IF NOT EXISTS ix_artifacts_data_gin ON run_artifacts USING gin (data jsonb_path_ops);
ALTER TABLE run_artifacts ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------- conversations
-- Persistent chat history. `topic_id` is the owner/group key (project has no
-- auth); `run_id` is the corpus a conversation's RAG retrieves against.
CREATE TABLE IF NOT EXISTS conversations (
    id             text PRIMARY KEY,
    topic_id       text NOT NULL,
    run_id         text NOT NULL,
    title          text NOT NULL DEFAULT 'New chat',
    summary        text NOT NULL DEFAULT '',
    archived_count integer NOT NULL DEFAULT 0,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_conversations_topic
    ON conversations (topic_id, updated_at DESC);
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS owner_email text;
CREATE INDEX IF NOT EXISTS ix_conversations_owner ON conversations (owner_email);
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------- messages
-- Append-only full history (never deleted by memory compaction). The file
-- working-set holds only the compacted recent turns; the DB keeps everything.
CREATE TABLE IF NOT EXISTS messages (
    id              bigserial PRIMARY KEY,
    conversation_id text NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            text NOT NULL,
    content         text NOT NULL DEFAULT '',
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_messages_convo
    ON messages (conversation_id, created_at);
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
