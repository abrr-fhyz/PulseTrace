# Ingestion Layer (`lib/ingest/`)

Parsing, cleaning, validation, and cataloging for documents entering the
pipeline. The layer is **additive and composable**: each module is usable on
its own, and nothing in the existing connector/agent/store path is rewired.
Wire it in incrementally where it adds value.

## Modules

| Module | Responsibility | Key API |
|--------|----------------|---------|
| `html_clean.py` | BeautifulSoup HTML → clean text | `clean_html`, `extract_structured` |
| `tabular.py` | pandas normalization of post batches | `normalize_posts`, `posts_to_frame`, `clean_frame` |
| `models.py` | Pydantic validation of entities | `PostModel`, `EnrichedPost`, `validate_posts` |
| `schemas.py` | Versioned JSON Schema for persisted docs | `validate_document`, `assert_valid`, `get_schema` |
| `catalog.py` | Normalization rules + stable IDs + index | `Catalog`, `stable_id`, `normalize_*` |

Every module is ≤200 lines, dependency-light, and TDD-covered in
`tests/test_ingest_*.py` (58 tests).

## Data flow

```
raw HTML ──html_clean.clean_html──▶ clean text
                                      │
post dict ◀───────────────────────────┘
   │
   ├─ models.validate_posts ──▶ (PostModel[], errors[])   ← validate after extraction
   │
   ├─ tabular.normalize_posts ─▶ DataFrame                ← bulk dedup / null / type fix
   │
   ├─ catalog.Catalog.add ─────▶ stable catalog_id        ← normalize + content dedup + index
   │
   └─ EnrichedPost(...)        ─▶ validated enriched record ← re-validate after enrichment
                                      │
                                      ▼
                       schemas.assert_valid(doc, "post")  ← gate before store.write_json
                                      │
                                      ▼
                                 data/runs/<id>/posts.json
```

## Validation strategy

Two layers, different jobs:

- **Pydantic (`models.py`)** — *in-process* validation of Python objects at the
  boundaries: immediately after extraction (`validate_post`/`validate_posts`)
  and again after enrichment (`EnrichedPost`). Coerces, applies defaults, and
  enforces business rules (non-empty text, http(s) URLs, non-negative
  engagement, sentiment ∈ {positive, neutral, negative, mixed}, score ∈ [0,1]).
  Batch helper returns `(valid_models, [(index, diagnostic)])` so one bad row
  never aborts a run — log and continue, per project error-handling rules.

- **JSON Schema (`schemas.py`)** — *at-rest* validation of documents about to be
  persisted. Schemas live in a `REGISTRY` keyed by name → version, so the shape
  can evolve (`post@1.0`, `run@1.0`) without breaking historical runs.
  `validate_document` returns every violation with a JSON-path;
  `assert_valid` raises `SchemaValidationError` with the full list.

Pydantic guards the live objects; JSON Schema guards the persisted bytes.

## Cataloging

`stable_id(source, text)` produces a deterministic `cat:<sha1[:16]>` that is
insensitive to case and surrounding whitespace, so re-fetching the same post
maps to one entry. `Catalog` indexes entries by that id, normalizes `author`
(strips `/u/`, `@`, lowercases) and `url` (drops `utm_*`/`fbclid`/`ref` tracking
params, trailing slash, lowercases host) on insert, dedups by content, and
offers `get`, `by_source`, `all`, `in`, and `len`.

## Lifecycle example: ingest → enrich → persist

```python
from lib.ingest.html_clean import clean_html
from lib.ingest.models import validate_posts, EnrichedPost
from lib.ingest.tabular import normalize_posts
from lib.ingest.catalog import Catalog
from lib.ingest.schemas import assert_valid

# 1. INGEST — clean raw HTML coming off a connector
raw = [{"id": "reddit:1", "source": "reddit",
        "text": clean_html("<p>Great <b>phone</b></p><script>x()</script>"),
        "url": "https://reddit.com/r/x/1/?utm_source=feed"}]

# 2. VALIDATE post-extraction (bad rows surfaced, not fatal)
valid, errors = validate_posts(raw)
for idx, diag in errors:
    log.warning("dropping row %d: %s", idx, diag)

# 3. NORMALIZE in bulk (dedup / nulls / types)
df = normalize_posts([m.model_dump() for m in valid])

# 4. CATALOG — stable ids + normalized author/url + content dedup
cat = Catalog()
for rec in df.to_dict("records"):
    cat.add(rec)

# 5. ENRICH + re-validate
enriched = EnrichedPost(**cat.all()[0], cluster_id=2,
                        sentiment="positive", score=0.91)

# 6. PERSIST — schema gate before write
doc = enriched.model_dump()
assert_valid(doc, "post")        # raises SchemaValidationError if malformed
# store.write_json(run_id, "posts.json", [doc])
```

## Dependencies

`beautifulsoup4` (stdlib `html.parser` backend — no lxml), `pandas`,
`pydantic>=2`, `jsonschema`. All added to `requirements.txt`.
