# Authentication + Per-User Data Isolation — Design

**Date:** 2026-06-10
**Branch:** `feat/authenticate` → PR to `shyan`
**Status:** Approved (brainstorm)

## Goal

Add real user authentication to PulseTrace and scope all chat history and
search (run) history to the owning user. Today the app has no auth: `/` renders
the dashboard directly, and every user sees every run and every conversation
(`schema.sql` literally notes "project has no auth").

Two user-facing requirements:

1. Sign-up / sign-in / password-recovery UI, then a backend that verifies it.
2. Each authenticated user sees **only their own** chat history and search
   history — never another user's.

## Decisions (locked)

| Decision | Choice | Rationale |
|---|---|---|
| Identity store | **Real Supabase Auth** (gotrue email/password) | Reuses the existing Supabase project; we never hash/store passwords ourselves. |
| Isolation layer | **App-layer `owner_email` column** + query filters | Works with the existing fast psycopg2 (`postgres` role) hot path, which bypasses RLS. No query rerouting. |
| Google OAuth | **UI kept, backend deferred** | Ship email/password first. Google button stays visible but its click shows "coming soon" until a later OAuth pass. |
| Legacy ownerless data | **Hidden from everyone** (`owner_email IS NULL` invisible) | Cleanest isolation guarantee; no backfill. |
| Gate when Supabase unconfigured | **Bypass (single-user local mode)** | Keeps existing dev/test flow working; matches `db/` additive + fail-safe ethos. |

## Architecture

Server-side auth. The browser never calls Supabase directly; the auth UI
`fetch`es Flask endpoints, Flask calls Supabase gotrue, and Flask owns a
signed-cookie session. One trust boundary, and the frontend keeps its
no-build-step rule.

```
Browser (auth.html)  --fetch-->  Flask /auth/*  -->  db/auth_users.py  -->  Supabase gotrue
       ^                              | sets Flask session[user_email]
       +---- redirect /login <-- before_request gate (401 api / 302 page)
```

**Gate posture:** the `before_request` gate is active whenever Supabase auth is
configured (URL + key present). When those creds are absent the gate is
bypassed so the app still runs as a single-user local instance — existing tests
and local dev are unaffected.

## Components

Each unit has one responsibility, a clear interface, and is independently
testable.

### `templates/auth.html` (+ themed CSS)
Login / signup / recovery views ported from the AI-Studio `zip(1)` export.
Adapted to the app's existing CSS theme tokens (dark default) rather than the
zip's parallel purple palette (`ui-match-theme-vars` memory). The Google button
is kept but inert (shows "coming soon"). Forms submit via `fetch` to `/auth/*`,
JS renders inline success/error.

- **Interface:** rendered at `GET /login`. Posts to `/auth/{signup,login,recover}`.
- **Depends on:** app theme variables.

### `db/auth_users.py`
**Stateless** gotrue helpers — a fresh `create_client(url, anon_key)` per call.
Deliberately NOT the `SupabaseAuthClient` singleton (that holds the shared
*dev-account* session; reusing it would conflate users).

- **Interface:**
  - `sign_up(email, password) -> AuthResult`
  - `sign_in(email, password) -> AuthResult`
  - `reset_password(email) -> AuthResult`
  - `auth_configured() -> bool`
  - `AuthResult` = `{ok: bool, email: str|None, access_token: str|None, error: str|None}`
- **Depends on:** `supabase-py` (heavy optional dep; absent → `auth_configured()` False).
- **Fail-safe:** gotrue exceptions degrade to `AuthResult(ok=False, error=...)`, never raise into Flask.

### `lib/auth.py`
Flask session glue.

- **Interface:**
  - `current_user() -> str|None` (email from `session`)
  - `login_user(email, access_token)` / `logout_user()`
  - `auth_active() -> bool` (Supabase configured → gate on)
  - `require_auth(view)` decorator — 401 JSON for API/data routes, 302→`/login` for pages.
- **Depends on:** flask, `db/auth_users.auth_configured`.

### `server.py` additions
- `GET /login` → renders `auth.html` (redirects to `/` if already authed).
- `POST /auth/signup`, `POST /auth/login`, `POST /auth/recover` → call `db/auth_users`, set session on success, return `{ok, error}`.
- `POST /auth/logout` → clear session.
- `before_request` gate: when `auth_active()` and no session, block protected routes (allow `/login`, `/auth/*`, static, health).
- Thread `owner_email = current_user()` into run creation (`/run`, `/api/agent/run`) and chat creation.
- `app.secret_key` from `FLASK_SECRET_KEY` env (random per-process fallback for dev).

### Data layer (isolation)
- **`db/schema.sql`:** idempotent `ALTER TABLE runs ADD COLUMN IF NOT EXISTS owner_email text;` and same for `conversations`; index on `owner_email`.
- **`db/supabase_client.py`:**
  - `upsert_run` / `upsert_conversation` persist `owner_email`.
  - `list_runs(owner_email)`, `list_conversations(topic_id, owner_email)` filter `WHERE owner_email = %s`.
  - `delete_run` / `delete_conversation` / `get_conversation` / `get_messages` enforce ownership.
- **Disk path:** `run.json` meta gets `owner_email`; `_disk_runs` filters by owner; `chat_store` threads inherit ownership from their `run_id`.
- **`_user_owns_run(run_id, email)`** guard used by all `/chat/*` routes (thread access flows from run ownership).
- **Legacy:** `owner_email IS NULL` rows never match a logged-in user → invisible.

## Data flow

1. Unauthenticated request to `/` → gate → 302 `/login`.
2. `POST /auth/login` → gotrue verifies → `session[user_email]` set → 200 `{ok:true}` → JS redirects `/`.
3. `GET /runs`, `/chat/runs`, `/chat/threads` → filtered by `current_user()`.
4. `POST /run` → run created with `owner_email = current_user()` in `runs` + `run.json`.
5. `POST /auth/logout` → session cleared → `/login`.

## Error handling

- gotrue failures (wrong password, user already exists, weak password) → friendly `{ok:false, error}`; UI shows inline.
- Gate: 401 JSON for API/data routes, 302 for pages.
- Supabase unreachable during login → `AuthResult(ok=False, error="auth service unavailable")`; no crash.
- Connector/agent loop behaviour unchanged (auth is orthogonal).

## Testing

- `db/auth_users.py`: mocked `create_client` — sign_up / sign_in success + failure; `auth_configured` false when dep/creds absent.
- Isolation: assert `owner_email` is bound in list/delete SQL params (mock cursor); `list_runs` omits NULL-owner rows.
- `_user_owns_run` true/false.
- Gate (Flask test client): no session → 401/redirect; valid session → passes; auth-unconfigured → bypass.
- Test files mirror module paths: `tests/test_auth_users.py`, `tests/test_auth_gate.py`, `tests/test_run_isolation.py`.

## Step plan (UI first, then backend)

1. **UI** — `auth.html` + themed CSS, `GET /login`, logout/user chip in dashboard. Forms wired to `/auth/*` endpoints that return "not configured" until Step 2. Visually complete and reviewable. Google button inert ("coming soon").
2. **Auth backend** — `db/auth_users.py`, `lib/auth.py`, real `/auth/*`, `before_request` gate, session secret.
3. **Isolation** — `owner_email` column + migrations, filtered list/read/delete queries, run + chat owner stamping, `_user_owns_run` guard, tests.

## Non-goals (this pass)

- Google OAuth backend (UI placeholder only).
- Postgres RLS enforcement (we isolate at the app layer).
- Backfilling existing ownerless data.
- Roles / permissions beyond per-user ownership.

## CLAUDE.md note

Project memory lists "Auth" as a non-goal. This feature is an explicit,
user-requested override; the non-goal line will be updated when the work lands.
