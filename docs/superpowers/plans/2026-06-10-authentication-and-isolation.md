# Authentication + Per-User Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real Supabase email/password authentication to PulseTrace and scope every run (search) and chat conversation to its owning user, so no user can see another user's history.

**Architecture:** Server-side auth — the browser auth UI `fetch`es Flask `/auth/*` endpoints, Flask calls Supabase gotrue via a stateless helper, and Flask owns a signed-cookie session. Isolation is enforced at the app layer with an `owner_email` column on `runs` + `conversations` and an `owner.json` side file per run dir; every list/read/delete filters by the logged-in user. When Supabase auth is unconfigured the gate is bypassed (single-user local mode) so existing dev/tests are unaffected.

**Tech Stack:** Python 3.12, Flask (signed-cookie session), supabase-py (gotrue), psycopg2, pytest + unittest.mock. Frontend: vanilla HTML/CSS/JS (no build step), app CSS theme tokens.

**Spec:** `docs/superpowers/specs/2026-06-10-authentication-and-isolation-design.md`

---

## File Structure

**Step 1 — UI**
- Create `static/css/auth.css` — auth page styling, mapped to app theme tokens.
- Create `templates/auth.html` — login/signup/recovery views + inert Google button + fetch JS.
- Modify `server.py` — add `GET /login` route; add placeholder `/auth/*` endpoints (real in Step 2).
- Modify `templates/partials/_app.html` (or the dashboard header partial) — user chip + logout button.

**Step 2 — Auth backend**
- Create `db/auth_users.py` — stateless gotrue helpers + `auth_configured()`.
- Create `lib/auth.py` — Flask session helpers, `require_auth`, `auth_active()`.
- Modify `db/__init__.py` — export auth_users helpers.
- Modify `server.py` — real `/auth/{signup,login,logout,recover}`, `before_request` gate, `app.secret_key`.
- Create `tests/test_auth_users.py`, `tests/test_auth_gate.py`.

**Step 3 — Isolation**
- Modify `db/schema.sql` — `owner_email` columns + indexes.
- Modify `db/models.py` — `RunRecord.owner_email`.
- Modify `lib/store.py` — `set_run_owner` / `get_run_owner`; mirror stamps owner.
- Modify `db/supabase_client.py` — owner-filtered `list_runs`, `upsert_run`, `list_conversations`, `upsert_conversation`, ownership-checked deletes.
- Modify `lib/chat_store.py` — thread `owner_email` plumbed into `_conv_row` / listing.
- Modify `server.py` — stamp owner on run + chat creation; `_user_owns_run` guard on `/chat/*` + run-scoped routes; owner-filter `_disk_runs`.
- Create `tests/test_run_isolation.py`, `tests/test_chat_isolation.py`.

---

## STEP 1 — UI

### Task 1: Auth page stylesheet (theme-mapped)

**Files:**
- Create: `static/css/auth.css`

The `zip(1)/src/index.css` defines its own purple palette. Re-express the same
design using the app's existing tokens from `static/css/tokens.css`
(`--bg`, `--panel`, `--panel2`, `--border`, `--text`, `--muted`,
`--accent2` ≈ lavender brand, `--accent3` ≈ light lavender). No new palette.

- [ ] **Step 1: Create the stylesheet**

```css
/* Auth pages — reuses app theme tokens (static/css/tokens.css). Dark-only. */
.auth-wrapper {
  position: relative; min-height: 100vh; display: flex; flex-direction: column;
  align-items: center; justify-content: center; padding: 1.5rem;
  overflow: hidden; box-sizing: border-box;
  background: var(--bg); color: var(--text);
  font-family: "Inter", ui-sans-serif, system-ui, sans-serif;
}
.auth-background-glow {
  position: absolute; inset: 0; pointer-events: none;
  background: radial-gradient(circle at center top, rgba(167,139,250,0.06) 0%, transparent 60%);
}
.auth-background-grid {
  position: absolute; inset: 0; opacity: 0.3; pointer-events: none;
  background-image:
    linear-gradient(var(--border) 1px, transparent 1px),
    linear-gradient(90deg, var(--border) 1px, transparent 1px);
  background-size: 64px 64px;
  -webkit-mask-image: radial-gradient(ellipse at center 20%, #000 20%, transparent 80%);
  mask-image: radial-gradient(ellipse at center 20%, #000 20%, transparent 80%);
}
.auth-brand { position: relative; z-index: 10; margin-bottom: 2rem; text-align: center; }
.brand-badge {
  display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.375rem 1rem;
  border: 1px solid var(--border); border-radius: 9999px;
  background: var(--panel); backdrop-filter: blur(12px);
  font-size: 0.875rem; font-weight: 500; color: var(--accent2);
}
.brand-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--accent2); box-shadow: 0 0 8px rgba(167,139,250,0.8);
}
.auth-card {
  position: relative; z-index: 10; width: 100%; max-width: 28rem;
  background: var(--panel); border: 1px solid var(--border); border-radius: 1rem;
  padding: 2rem; box-shadow: var(--card-shadow); overflow: hidden; box-sizing: border-box;
}
.auth-card-highlight {
  position: absolute; top: 0; left: 0; right: 0; height: 3px;
  background: linear-gradient(to right, var(--accent2), var(--accent3), var(--accent2));
  opacity: 0.8;
}
.auth-view { display: flex; flex-direction: column; }
.auth-view.hidden { display: none; }
.auth-view.active { animation: authRise 0.4s cubic-bezier(0.16,1,0.3,1) both; }
@keyframes authRise {
  from { opacity: 0; transform: translateY(12px); filter: blur(4px); }
  to   { opacity: 1; transform: translateY(0);    filter: blur(0); }
}
.auth-title { margin: 0 0 0.5rem; font-size: 1.5rem; font-weight: 700; color: var(--text); letter-spacing: -0.025em; }
.auth-subtitle { margin: 0 0 2rem; font-size: 0.875rem; color: var(--muted); line-height: 1.5; }
.auth-form { display: flex; flex-direction: column; gap: 1rem; }
.form-group { display: flex; flex-direction: column; }
.form-group label {
  font-size: 0.75rem; font-weight: 600; color: var(--muted); margin-bottom: 0.5rem;
  text-transform: uppercase; letter-spacing: 0.05em;
}
.label-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
.label-row label { margin-bottom: 0; }
.forgot-password { font-size: 0.75rem; font-weight: 500; color: var(--accent2); text-decoration: none; }
.forgot-password:hover { opacity: 0.8; }
.input-wrapper { position: relative; }
.input-icon { position: absolute; left: 1rem; top: 50%; transform: translateY(-50%); width: 1rem; height: 1rem; color: var(--muted); }
.input-wrapper input {
  width: 100%; box-sizing: border-box; background: var(--panel2);
  border: 1px solid var(--border); color: var(--text); border-radius: 0.75rem;
  padding: 0.75rem 1rem 0.75rem 2.75rem; font-size: 0.875rem; font-family: inherit;
  outline: none; transition: all 0.2s;
}
.input-wrapper input:focus { border-color: var(--accent2); box-shadow: 0 0 0 4px rgba(167,139,250,0.15); }
.btn-primary {
  margin-top: 0.5rem; width: 100%; display: flex; align-items: center; justify-content: center; gap: 0.5rem;
  background: linear-gradient(135deg, var(--accent3) 0%, var(--accent2) 50%, #7c5cf0 100%);
  color: #0a0a0f; font-size: 1rem; font-weight: 600; padding: 0.75rem 1rem; border-radius: 0.75rem;
  border: none; cursor: pointer; box-shadow: 0 12px 34px -8px rgba(167,139,250,0.7); transition: all 0.3s ease; font-family: inherit;
}
.btn-primary:hover { transform: translateY(-2px); box-shadow: 0 20px 48px -8px rgba(167,139,250,0.88); }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
.btn-icon { width: 1rem; height: 1rem; }
.btn-back {
  width: 2.5rem; height: 2.5rem; border-radius: 50%; display: flex; align-items: center; justify-content: center;
  background: var(--panel2); border: 1px solid var(--border); color: var(--muted); cursor: pointer;
  transition: all 0.2s; margin-bottom: 1.5rem; padding: 0;
}
.btn-back:hover { color: var(--text); border-color: var(--accent2); }
.auth-divider { position: relative; display: flex; align-items: center; margin: 1.75rem 0; }
.auth-divider::before, .auth-divider::after { content: ""; flex-grow: 1; border-top: 1px solid var(--border); }
.auth-divider span { flex-shrink: 0; margin: 0 1rem; color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 500; }
.btn-google {
  width: 100%; background: var(--panel2); border: 1px solid var(--border); color: var(--text);
  border-radius: 0.75rem; padding: 0.75rem 1rem; display: flex; align-items: center; justify-content: center;
  gap: 0.75rem; font-size: 1rem; font-weight: 500; cursor: pointer; transition: all 0.2s; font-family: inherit;
}
.btn-google:hover { border-color: var(--accent2); background: rgba(52,52,63,0.5); }
.google-icon { width: 1.25rem; height: 1.25rem; }
.auth-switch { margin-top: 2rem; text-align: center; font-size: 0.875rem; color: var(--muted); }
.auth-switch a { color: var(--accent2); font-weight: 600; text-decoration: none; }
.auth-switch a:hover { opacity: 0.8; }
.auth-footer { margin-top: 2rem; text-align: center; font-size: 0.75rem; font-weight: 500; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; }
.auth-msg { margin-top: 1rem; font-size: 0.8125rem; text-align: center; min-height: 1.2em; }
.auth-msg.error { color: var(--neg); }
.auth-msg.ok { color: var(--pos); }
```

- [ ] **Step 2: Commit**

```bash
git add static/css/auth.css
git commit -m "feat(auth): themed auth page stylesheet"
```

---

### Task 2: Auth page template

**Files:**
- Create: `templates/auth.html`

Ported from `zip(1)/index.html` (login / signup / recovery views). Differences:
loads app `tokens.css` + new `auth.css`; forms call `/auth/*` via `fetch`; the
Google button is **inert** (shows a "coming soon" message); a status line shows
errors/success.

- [ ] **Step 1: Create the template**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>PulseTrace — Sign in</title>
  <script>document.documentElement.dataset.theme = "dark";</script>
  <link rel="stylesheet" href="{{ url_for('static', filename='css/tokens.css') }}">
  <link rel="stylesheet" href="{{ url_for('static', filename='css/auth.css') }}">
</head>
<body>
  <div class="auth-wrapper">
    <div class="auth-background-glow"></div>
    <div class="auth-background-grid"></div>
    <div class="auth-brand"><div class="brand-badge"><span class="brand-dot"></span>PulseTrace</div></div>

    <div class="auth-card" id="auth-card">
      <div class="auth-card-highlight"></div>

      <!-- LOGIN -->
      <div id="view-login" class="auth-view active">
        <h2 class="auth-title">Welcome back</h2>
        <p class="auth-subtitle">Sign in to access your dashboard.</p>
        <form class="auth-form" data-action="login">
          <div class="form-group"><label>Email Address</label>
            <div class="input-wrapper">
              <svg class="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>
              <input name="email" type="email" placeholder="name@company.com" required>
            </div>
          </div>
          <div class="form-group">
            <div class="label-row"><label>Password</label>
              <a href="#" class="forgot-password" onclick="switchView('recovery');return false;">Forgot password?</a></div>
            <div class="input-wrapper">
              <svg class="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
              <input name="password" type="password" placeholder="••••••••" required>
            </div>
          </div>
          <button type="submit" class="btn-primary">Sign In</button>
        </form>
        <div class="auth-divider"><span>Or continue with</span></div>
        <button type="button" class="btn-google" data-google>
          <svg class="google-icon" viewBox="0 0 24 24"><path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/><path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/><path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/><path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/></svg>
          Sign in with Google
        </button>
        <p class="auth-switch">Don't have an account? <a href="#" onclick="switchView('signup');return false;">Request access</a></p>
      </div>

      <!-- SIGNUP -->
      <div id="view-signup" class="auth-view hidden">
        <h2 class="auth-title">Create account</h2>
        <p class="auth-subtitle">Join us to deploy intelligence agents.</p>
        <form class="auth-form" data-action="signup">
          <div class="form-group"><label>Full Name</label>
            <div class="input-wrapper">
              <svg class="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
              <input name="name" type="text" placeholder="Jane Doe">
            </div>
          </div>
          <div class="form-group"><label>Email Address</label>
            <div class="input-wrapper">
              <svg class="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>
              <input name="email" type="email" placeholder="name@company.com" required>
            </div>
          </div>
          <div class="form-group"><label>Password</label>
            <div class="input-wrapper">
              <svg class="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
              <input name="password" type="password" placeholder="•••••••• (min 6 chars)" required minlength="6">
            </div>
          </div>
          <button type="submit" class="btn-primary">Create Account</button>
        </form>
        <p class="auth-switch">Already have an account? <a href="#" onclick="switchView('login');return false;">Sign in</a></p>
      </div>

      <!-- RECOVERY -->
      <div id="view-recovery" class="auth-view hidden">
        <button type="button" class="btn-back" onclick="switchView('login')" aria-label="Back to login">
          <svg style="width:1.25rem;height:1.25rem" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 19-7-7 7-7"/><path d="M19 12H5"/></svg>
        </button>
        <h2 class="auth-title">Reset password</h2>
        <p class="auth-subtitle" style="margin-bottom:2rem;">Enter your account email and we'll send a reset link.</p>
        <form class="auth-form" data-action="recover">
          <div class="form-group"><label>Email Address</label>
            <div class="input-wrapper">
              <svg class="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>
              <input name="email" type="email" placeholder="name@company.com" required>
            </div>
          </div>
          <button type="submit" class="btn-primary">Send Reset Link</button>
        </form>
      </div>

      <div class="auth-msg" id="auth-msg"></div>
    </div>
    <p class="auth-footer">Secure · Per-user workspace</p>
  </div>

  <script>
    function switchView(viewId) {
      document.querySelectorAll('.auth-view').forEach(el => { el.classList.remove('active'); el.classList.add('hidden'); });
      const sel = document.getElementById('view-' + viewId);
      sel.classList.remove('hidden'); void sel.offsetWidth; sel.classList.add('active');
      setMsg('', '');
    }
    function setMsg(text, kind) {
      const m = document.getElementById('auth-msg');
      m.textContent = text; m.className = 'auth-msg' + (kind ? ' ' + kind : '');
    }
    async function postJSON(url, body) {
      const r = await fetch(url, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
      });
      let data = {}; try { data = await r.json(); } catch (e) {}
      return { ok: r.ok && data.ok !== false, data };
    }
    document.querySelectorAll('form[data-action]').forEach(form => {
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const action = form.dataset.action;
        const btn = form.querySelector('button[type=submit]');
        const fields = Object.fromEntries(new FormData(form).entries());
        btn.disabled = true; setMsg('Working…', '');
        const { ok, data } = await postJSON('/auth/' + action, fields);
        btn.disabled = false;
        if (ok) {
          if (action === 'recover') { setMsg('Check your inbox for a reset link.', 'ok'); }
          else if (action === 'signup') { setMsg(data.message || 'Account created — you can sign in.', 'ok'); switchView('login'); }
          else { window.location.href = '/'; }
        } else {
          setMsg(data.error || 'Something went wrong.', 'error');
        }
      });
    });
    document.querySelectorAll('[data-google]').forEach(b =>
      b.addEventListener('click', () => setMsg('Google sign-in is coming soon.', '')));
  </script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add templates/auth.html
git commit -m "feat(auth): login/signup/recovery page (Google inert)"
```

---

### Task 3: `/login` route + placeholder `/auth/*` endpoints

**Files:**
- Modify: `server.py` (add after the `index()` route, ~line 90)

Step 1 wires the page so it renders and reacts. The `/auth/*` endpoints return a
graceful "not configured" message; Step 2 replaces their bodies with real logic.

- [ ] **Step 1: Add routes**

```python
@app.route("/login")
def login_page():
    return render_template("auth.html")


@app.route("/auth/login", methods=["POST"])
@app.route("/auth/signup", methods=["POST"])
@app.route("/auth/recover", methods=["POST"])
def auth_placeholder():
    # Replaced with real Supabase auth in Step 2.
    return jsonify({"ok": False, "error": "Authentication is not configured yet."}), 501
```

- [ ] **Step 2: Verify the page renders**

Run: `.venv/bin/python -c "import server; c=server.app.test_client(); r=c.get('/login'); print(r.status_code); assert b'Welcome back' in r.data"`
Expected: prints `200`, no assertion error.

- [ ] **Step 3: Commit**

```bash
git add server.py
git commit -m "feat(auth): /login page route + placeholder auth endpoints"
```

---

### Task 4: User chip + logout in dashboard header

**Files:**
- Modify: `templates/partials/_app.html` (header region — inspect the file and place inside the top header bar)

Adds a small user chip + logout button. It reads the current user from a global
`window.__USER__` injected by Step 2's index route; for Step 1 it degrades to an
empty chip. Logout posts to `/auth/logout` then redirects to `/login`.

- [ ] **Step 1: Locate the header**

Run: `grep -n "header\|topbar\|brand\|logo" templates/partials/_app.html | head`
Expected: identifies the top bar element to append into.

- [ ] **Step 2: Add the chip markup** (place at the end of the header bar element)

```html
<div id="user-chip" class="user-chip" style="display:none;align-items:center;gap:.5rem;margin-left:auto;">
  <span id="user-email" style="font-size:.8125rem;color:var(--muted);"></span>
  <button id="logout-btn" class="ghost-btn" title="Sign out"
          style="background:var(--panel2);border:1px solid var(--border);color:var(--text);border-radius:.5rem;padding:.35rem .6rem;cursor:pointer;font-size:.8125rem;">
    Sign out
  </button>
</div>
<script>
  (function () {
    const email = (window.__USER__ || "").trim();
    const chip = document.getElementById('user-chip');
    if (email) { document.getElementById('user-email').textContent = email; chip.style.display = 'flex'; }
    document.getElementById('logout-btn').addEventListener('click', async () => {
      try { await fetch('/auth/logout', { method: 'POST' }); } catch (e) {}
      window.location.href = '/login';
    });
  })();
</script>
```

- [ ] **Step 3: Verify markup loads**

Run: `.venv/bin/python -c "import server; c=server.app.test_client(); r=c.get('/'); print(r.status_code); assert b'logout-btn' in r.data"`
Expected: prints `200`, no assertion error. (Gate is added in Step 2; `/` is open now.)

- [ ] **Step 4: Commit**

```bash
git add templates/partials/_app.html
git commit -m "feat(auth): dashboard user chip + sign-out button"
```

---

## STEP 2 — AUTH BACKEND

### Task 5: Stateless gotrue helpers (`db/auth_users.py`)

**Files:**
- Create: `db/auth_users.py`
- Test: `tests/test_auth_users.py`

A fresh `create_client(url, anon_key)` per call — deliberately NOT the
`SupabaseAuthClient` singleton (that holds the shared dev-account session).

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations
from unittest.mock import MagicMock, patch
from db import auth_users


def _fake_client(user_email="u@x.com", token="tok", raises=None):
    client = MagicMock()
    if raises is not None:
        client.auth.sign_in_with_password.side_effect = raises
        client.auth.sign_up.side_effect = raises
    else:
        res = MagicMock()
        res.user.email = user_email
        res.session.access_token = token
        client.auth.sign_in_with_password.return_value = res
        client.auth.sign_up.return_value = res
    return client


def test_sign_in_success():
    with patch.object(auth_users, "_make_client", return_value=_fake_client()):
        r = auth_users.sign_in("u@x.com", "pw")
    assert r.ok is True and r.email == "u@x.com" and r.access_token == "tok" and r.error is None


def test_sign_in_failure_degrades():
    with patch.object(auth_users, "_make_client", return_value=_fake_client(raises=ValueError("bad creds"))):
        r = auth_users.sign_in("u@x.com", "wrong")
    assert r.ok is False and r.email is None and "bad creds" in (r.error or "")


def test_sign_up_success():
    with patch.object(auth_users, "_make_client", return_value=_fake_client()):
        r = auth_users.sign_up("u@x.com", "pw123456")
    assert r.ok is True and r.email == "u@x.com"


def test_auth_configured_false_without_env(monkeypatch):
    for k in ("SUPABASE_URL", "SUPABASE_PROJECT_URL", "SUPABASE_PUBLISHABLE_KEY",
              "SUPABASE_ANON_KEY", "SUPABASE_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert auth_users.auth_configured() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_auth_users.py -v`
Expected: FAIL — `ModuleNotFoundError`/`AttributeError` (module not written).

- [ ] **Step 3: Write the implementation**

```python
"""Stateless Supabase gotrue helpers for per-user auth.

Unlike db.supabase_auth.SupabaseAuthClient (a singleton signed in as the shared
dev account), these functions create a throwaway client per call so each call
acts on behalf of one end user. All failures degrade to AuthResult(ok=False);
they never raise into Flask.

Env (first hit wins):
    URL : SUPABASE_URL > SUPABASE_PROJECT_URL
    KEY : SUPABASE_PUBLISHABLE_KEY > SUPABASE_ANON_KEY > SUPABASE_KEY
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

log = logging.getLogger("pulsetrace.db.auth_users")

try:  # heavy optional dep
    from supabase import create_client
    _HAVE_SUPABASE = True
except ImportError:  # pragma: no cover
    _HAVE_SUPABASE = False


@dataclass
class AuthResult:
    ok: bool
    email: str | None = None
    access_token: str | None = None
    error: str | None = None
    message: str | None = None


def _url() -> str:
    return os.environ.get("SUPABASE_URL") or os.environ.get("SUPABASE_PROJECT_URL", "")


def _key() -> str:
    for name in ("SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY", "SUPABASE_KEY"):
        v = os.environ.get(name)
        if v:
            return v
    return ""


def auth_configured() -> bool:
    return bool(_url() and _key()) and _HAVE_SUPABASE


def _make_client():
    return create_client(_url(), _key())


def _extract(res) -> tuple[str | None, str | None]:
    user = getattr(res, "user", None)
    session = getattr(res, "session", None)
    email = getattr(user, "email", None) if user else None
    token = getattr(session, "access_token", None) if session else None
    return email, token


def sign_in(email: str, password: str) -> AuthResult:
    if not auth_configured():
        return AuthResult(False, error="Authentication is not configured.")
    try:
        res = _make_client().auth.sign_in_with_password({"email": email, "password": password})
        em, tok = _extract(res)
        if not em:
            return AuthResult(False, error="Invalid email or password.")
        return AuthResult(True, email=em, access_token=tok)
    except Exception as exc:  # gotrue/httpx raise varied types; degrade
        log.warning("sign_in failed for %s: %s", email, exc)
        return AuthResult(False, error=str(exc) or "Invalid email or password.")


def sign_up(email: str, password: str) -> AuthResult:
    if not auth_configured():
        return AuthResult(False, error="Authentication is not configured.")
    try:
        res = _make_client().auth.sign_up({"email": email, "password": password})
        em, tok = _extract(res)
        if not em:
            return AuthResult(False, error="Could not create the account.")
        return AuthResult(True, email=em, access_token=tok,
                          message="Account created. You can sign in now.")
    except Exception as exc:
        log.warning("sign_up failed for %s: %s", email, exc)
        return AuthResult(False, error=str(exc) or "Could not create the account.")


def reset_password(email: str) -> AuthResult:
    if not auth_configured():
        return AuthResult(False, error="Authentication is not configured.")
    try:
        _make_client().auth.reset_password_for_email(email)
        return AuthResult(True, email=email, message="Reset link sent if the account exists.")
    except Exception as exc:
        log.warning("reset_password failed for %s: %s", email, exc)
        return AuthResult(False, error=str(exc) or "Could not send a reset link.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_auth_users.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add db/auth_users.py tests/test_auth_users.py
git commit -m "feat(auth): stateless Supabase gotrue helpers + tests"
```

---

### Task 6: Flask session helpers + gate (`lib/auth.py`)

**Files:**
- Create: `lib/auth.py`
- Test: `tests/test_auth_gate.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations
from unittest.mock import patch
import flask
from lib import auth


def _app():
    app = flask.Flask(__name__)
    app.secret_key = "test"
    @app.route("/protected")
    @auth.require_auth
    def protected():
        return "secret"
    @app.route("/api/protected")
    @auth.require_auth
    def api_protected():
        return flask.jsonify(ok=True)
    return app


def test_require_auth_redirects_page_when_active_and_anon():
    app = _app()
    with patch.object(auth, "auth_active", return_value=True):
        r = app.test_client().get("/protected")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_require_auth_401_for_api_when_active_and_anon():
    app = _app()
    with patch.object(auth, "auth_active", return_value=True):
        r = app.test_client().get("/api/protected")
    assert r.status_code == 401


def test_require_auth_bypass_when_inactive():
    app = _app()
    with patch.object(auth, "auth_active", return_value=False):
        r = app.test_client().get("/protected")
    assert r.status_code == 200 and r.data == b"secret"


def test_require_auth_passes_with_session():
    app = _app()
    with patch.object(auth, "auth_active", return_value=True):
        client = app.test_client()
        with client.session_transaction() as s:
            s["user_email"] = "u@x.com"
        r = client.get("/protected")
    assert r.status_code == 200


def test_current_user_reads_session():
    app = _app()
    with app.test_request_context():
        flask.session["user_email"] = "a@b.com"
        assert auth.current_user() == "a@b.com"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_auth_gate.py -v`
Expected: FAIL — module `lib.auth` not found.

- [ ] **Step 3: Write the implementation**

```python
"""Flask session glue for per-user auth.

`auth_active()` is True only when Supabase auth is configured; otherwise the
whole app runs unauthenticated (single-user local mode) and `require_auth` is a
no-op. This keeps existing dev/test flows working without credentials.
"""
from __future__ import annotations

from functools import wraps

from flask import jsonify, redirect, request, session

from db.auth_users import auth_configured


def auth_active() -> bool:
    return auth_configured()


def current_user() -> str | None:
    return session.get("user_email")


def login_user(email: str, access_token: str | None = None) -> None:
    session["user_email"] = email
    if access_token:
        session["sb_access_token"] = access_token


def logout_user() -> None:
    session.pop("user_email", None)
    session.pop("sb_access_token", None)


def _wants_json() -> bool:
    return request.path.startswith("/api") or request.path.startswith("/auth") \
        or "application/json" in (request.headers.get("Accept") or "")


def require_auth(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not auth_active() or current_user():
            return view(*args, **kwargs)
        if _wants_json():
            return jsonify({"ok": False, "error": "Authentication required."}), 401
        return redirect("/login")
    return wrapper
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_auth_gate.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/auth.py tests/test_auth_gate.py
git commit -m "feat(auth): Flask session helpers + require_auth gate + tests"
```

---

### Task 7: Wire real auth endpoints + global gate + session secret

**Files:**
- Modify: `server.py` (imports near line 31; `app` config near line 34; replace `auth_placeholder` from Task 3; `index()` near line 88)

- [ ] **Step 1: Add imports + secret key + global gate**

Add to the import block (after `from lib import chat_store, chat_memory, chat_engine`):

```python
from lib import auth as auth_lib
from db import auth_users
```

After `app = Flask(__name__)` / `CORS(app)` (near line 35):

```python
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(32)

_AUTH_OPEN_PREFIXES = ("/login", "/auth/", "/static/", "/favicon")
_AUTH_OPEN_EXACT = {"/status"}


@app.before_request
def _auth_gate():
    if not auth_lib.auth_active():
        return None
    path = request.path
    if path in _AUTH_OPEN_EXACT or path.startswith(_AUTH_OPEN_PREFIXES):
        return None
    if auth_lib.current_user():
        return None
    if path.startswith("/api") or path.startswith("/chat") or path.startswith("/run") \
            or path in ("/runs", "/graph", "/events") \
            or "application/json" in (request.headers.get("Accept") or ""):
        return jsonify({"ok": False, "error": "Authentication required."}), 401
    return redirect("/login")
```

- [ ] **Step 2: Inject current user into the dashboard**

Replace the `index()` route body (near line 88-90) with:

```python
@app.route("/")
def index():
    return render_template("index.html", user_email=auth_lib.current_user() or "")
```

Then in `templates/index.html`, add inside `<head>` (after the theme script, before the CSS links):

```html
  <script>window.__USER__ = "{{ user_email }}";</script>
```

- [ ] **Step 3: Replace the placeholder auth endpoints**

Replace the `auth_placeholder` function (added in Task 3) with:

```python
@app.route("/login")
def login_page():
    if auth_lib.current_user():
        return redirect("/")
    return render_template("auth.html")


@app.route("/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json(force=True, silent=True) or {}
    res = auth_users.sign_in((data.get("email") or "").strip(), data.get("password") or "")
    if res.ok:
        auth_lib.login_user(res.email, res.access_token)
        return jsonify({"ok": True, "email": res.email})
    return jsonify({"ok": False, "error": res.error}), 401


@app.route("/auth/signup", methods=["POST"])
def auth_signup():
    data = request.get_json(force=True, silent=True) or {}
    res = auth_users.sign_up((data.get("email") or "").strip(), data.get("password") or "")
    if res.ok:
        return jsonify({"ok": True, "email": res.email, "message": res.message})
    return jsonify({"ok": False, "error": res.error}), 400


@app.route("/auth/recover", methods=["POST"])
def auth_recover():
    data = request.get_json(force=True, silent=True) or {}
    res = auth_users.reset_password((data.get("email") or "").strip())
    return (jsonify({"ok": True, "message": res.message}) if res.ok
            else (jsonify({"ok": False, "error": res.error}), 400))


@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    auth_lib.logout_user()
    return jsonify({"ok": True})
```

Note: this defines `login_page` here; delete the earlier `login_page` from Task 3
so the route isn't registered twice (Flask raises on duplicate endpoint names).

- [ ] **Step 4: Verify gate behavior both ways**

Run (gate off — no creds): `.venv/bin/python -m pytest tests/test_auth_gate.py tests/test_auth_users.py -v`
Expected: all pass.

Run (gate on): `.venv/bin/python -c "
import os
os.environ['SUPABASE_URL']='https://x.supabase.co'; os.environ['SUPABASE_ANON_KEY']='k'
import server
c=server.app.test_client()
r=c.get('/'); print('root', r.status_code)
assert r.status_code==302 and '/login' in r.headers['Location']
r=c.get('/runs'); print('runs', r.status_code); assert r.status_code==401
r=c.get('/login'); print('login', r.status_code); assert r.status_code==200
print('GATE OK')"`
Expected: prints `root 302`, `runs 401`, `login 200`, `GATE OK`.

- [ ] **Step 5: Commit**

```bash
git add server.py templates/index.html
git commit -m "feat(auth): real Supabase auth endpoints + global before_request gate"
```

---

## STEP 3 — PER-USER ISOLATION

### Task 8: `owner_email` schema + `RunRecord` field

**Files:**
- Modify: `db/schema.sql` (after the `runs` table block ~line 23; after `conversations` ~line 177)
- Modify: `db/models.py` (the `RunRecord` dataclass)

- [ ] **Step 1: Add idempotent migrations to schema.sql**

After the `runs` indexes (~line 23), add:

```sql
ALTER TABLE runs ADD COLUMN IF NOT EXISTS owner_email text;
CREATE INDEX IF NOT EXISTS ix_runs_owner ON runs (owner_email);
```

After the `conversations` index (~line 177), add:

```sql
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS owner_email text;
CREATE INDEX IF NOT EXISTS ix_conversations_owner ON conversations (owner_email);
```

- [ ] **Step 2: Add `owner_email` to RunRecord**

In `db/models.py`, add to the `RunRecord` dataclass a field (place after `meta`):

```python
    owner_email: str | None = None
```

Run: `grep -n "class RunRecord" -A 20 db/models.py`
Expected: confirm `owner_email` is now a field with default `None`.

- [ ] **Step 3: Commit**

```bash
git add db/schema.sql db/models.py
git commit -m "feat(isolation): owner_email column + RunRecord.owner_email"
```

---

### Task 9: Run owner side-file in `lib/store.py`

**Files:**
- Modify: `lib/store.py`
- Test: `tests/test_run_isolation.py`

The agent owns `run.json`, so owner is stored in a separate `owner.json` side
file that survives run.json rewrites. The DB mirror reads it onto `RunRecord`.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations
import importlib


def test_set_get_run_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("PULSETRACE_DATA_ROOT", str(tmp_path))
    import lib.store as store
    importlib.reload(store)
    store.set_run_owner("run1", "owner@x.com")
    assert store.get_run_owner("run1") == "owner@x.com"
    assert store.get_run_owner("missing") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_run_isolation.py::test_set_get_run_owner -v`
Expected: FAIL — `AttributeError: module 'lib.store' has no attribute 'set_run_owner'`.

- [ ] **Step 3: Implement the side file**

Add to `lib/store.py` (after `new_run_id`):

```python
_OWNER_FILE = "owner.json"


def set_run_owner(run_id: str, owner_email: str | None) -> None:
    if not owner_email:
        return
    (run_dir(run_id) / _OWNER_FILE).write_text(json.dumps({"owner_email": owner_email}))


def get_run_owner(run_id: str) -> str | None:
    p = ROOT / run_id / _OWNER_FILE
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text()).get("owner_email")
    except (json.JSONDecodeError, OSError):
        return None
```

Then in `_mirror_to_db`, in the `if name == "run.json":` branch, set the owner on
the record. Change the `RunRecord(...)` construction to include:

```python
                owner_email=get_run_owner(run_id),
```

(add it as the last keyword arg inside `RunRecord(...)`).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_run_isolation.py::test_set_get_run_owner -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/store.py tests/test_run_isolation.py
git commit -m "feat(isolation): per-run owner side-file + DB mirror stamping"
```

---

### Task 10: Owner-filtered run queries (`db/supabase_client.py`)

**Files:**
- Modify: `db/supabase_client.py` (`upsert_run` ~line 131, `list_runs` ~line 312, `delete_run` ~line 329)
- Test: `tests/test_run_isolation.py` (add)

`owner_email=None` means "no filter" (back-compat / local mode); a string filters.

- [ ] **Step 1: Write the failing test** (append to `tests/test_run_isolation.py`)

```python
from unittest.mock import MagicMock
from contextlib import contextmanager
from db.supabase_client import SupabaseClient


def _client_with_capture():
    c = SupabaseClient.__new__(SupabaseClient)
    c.enabled = True
    captured = {}
    cur = MagicMock()
    def _execute(sql, params=None):
        captured["sql"] = sql; captured["params"] = params
    cur.execute.side_effect = _execute
    cur.fetchall.return_value = []
    @contextmanager
    def _conn():
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        yield conn
    c._conn = _conn
    return c, captured


def test_list_runs_filters_by_owner():
    c, captured = _client_with_capture()
    c.list_runs(owner_email="me@x.com", limit=10)
    assert "owner_email = %s" in captured["sql"]
    assert "me@x.com" in captured["params"]


def test_list_runs_no_owner_no_filter():
    c, captured = _client_with_capture()
    c.list_runs(owner_email=None, limit=10)
    assert "owner_email = %s" not in captured["sql"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_run_isolation.py -k list_runs -v`
Expected: FAIL — `list_runs()` got an unexpected keyword `owner_email`.

- [ ] **Step 3: Update the three methods**

`upsert_run` — add `owner_email` to the INSERT (column list, values, and the
ON CONFLICT update). Replace the `cur.execute(...)` call in `upsert_run` with:

```python
                cur.execute(
                    """
                    INSERT INTO runs (run_id, topic, topic_id, sources, status,
                                      started_at, finished_at, n_posts, meta, owner_email)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (run_id) DO UPDATE SET
                        status      = EXCLUDED.status,
                        finished_at = EXCLUDED.finished_at,
                        n_posts     = EXCLUDED.n_posts,
                        meta        = EXCLUDED.meta,
                        owner_email = COALESCE(runs.owner_email, EXCLUDED.owner_email)
                    """,
                    (run.run_id, run.topic, run.topic_id, run.sources, run.status,
                     run.started_at, run.finished_at, run.n_posts,
                     psycopg2.extras.Json(run.meta) if _HAVE_PG else run.meta,
                     run.owner_email),
                )
```

(`COALESCE` keeps the original owner if a later status-only upsert passes None.)

`list_runs` — change the signature and query:

```python
    def list_runs(self, *, owner_email: str | None = None, limit: int = 50) -> list[dict] | None:
        if not self.enabled:
            return None
        try:
            where = "WHERE owner_email = %s" if owner_email else ""
            params: tuple = (owner_email, limit) if owner_email else (limit,)
            with self._conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT run_id, topic, started_at, finished_at, n_posts, status "
                    f"FROM runs {where} ORDER BY started_at DESC NULLS LAST LIMIT %s",
                    params,
                )
                return [dict(r) for r in cur.fetchall()]
        except psycopg2.Error as exc:
            log.error("list_runs failed: %s", exc)
            return None
```

`delete_run` — add an owner guard so a user can't delete another's run:

```python
    def delete_run(self, run_id: str, *, owner_email: str | None = None) -> bool:
        if not self.enabled:
            return False
        try:
            with self._conn() as conn, conn.cursor() as cur:
                if owner_email:
                    cur.execute("SELECT owner_email FROM runs WHERE run_id=%s", (run_id,))
                    row = cur.fetchone()
                    if row and row[0] not in (None, owner_email):
                        return False
                for table in ("run_artifacts", "clusters", "posts", "runs"):
                    cur.execute(f"DELETE FROM {table} WHERE run_id=%s", (run_id,))
            return True
        except psycopg2.Error as exc:
            log.error("delete_run(%s) failed: %s", run_id, exc)
            return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_run_isolation.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add db/supabase_client.py tests/test_run_isolation.py
git commit -m "feat(isolation): owner-filtered list/upsert/delete for runs"
```

---

### Task 11: Owner-filtered conversation queries (`db/supabase_client.py`)

**Files:**
- Modify: `db/supabase_client.py` (`upsert_conversation` ~line 378, `list_conversations` ~line 451)
- Test: `tests/test_chat_isolation.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations
from unittest.mock import MagicMock
from contextlib import contextmanager
from db.supabase_client import SupabaseClient


def _capture():
    c = SupabaseClient.__new__(SupabaseClient)
    c.enabled = True
    cap = {}
    cur = MagicMock()
    def _ex(sql, params=None):
        cap["sql"] = sql; cap["params"] = params
    cur.execute.side_effect = _ex
    cur.fetchall.return_value = []
    @contextmanager
    def _conn():
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        yield conn
    c._conn = _conn
    return c, cap


def test_list_conversations_filters_owner():
    c, cap = _capture()
    c.list_conversations("topic-x", owner_email="me@x.com")
    assert "owner_email = %s" in cap["sql"]
    assert "me@x.com" in cap["params"] and "topic-x" in cap["params"]


def test_list_conversations_no_owner():
    c, cap = _capture()
    c.list_conversations("topic-x", owner_email=None)
    assert "owner_email = %s" not in cap["sql"]
    assert "topic-x" in cap["params"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_chat_isolation.py -v`
Expected: FAIL — `list_conversations()` unexpected keyword `owner_email`.

- [ ] **Step 3: Update the two methods**

`upsert_conversation` — persist `owner_email`. Replace its `cur.execute(...)`:

```python
                cur.execute(
                    """
                    INSERT INTO conversations
                        (id, topic_id, run_id, title, summary, archived_count, owner_email, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s, now())
                    ON CONFLICT (id) DO UPDATE SET
                        title=EXCLUDED.title, summary=EXCLUDED.summary,
                        archived_count=EXCLUDED.archived_count,
                        owner_email=COALESCE(conversations.owner_email, EXCLUDED.owner_email),
                        updated_at=now()
                    """,
                    (conv["id"], conv["topic_id"], conv["run_id"],
                     conv.get("title", "New chat"), conv.get("summary", ""),
                     int(conv.get("archived_count", 0)), conv.get("owner_email")),
                )
```

`list_conversations` — add owner filter:

```python
    def list_conversations(self, topic_id: str, *, owner_email: str | None = None) -> list[dict]:
        if not self.enabled:
            return []
        try:
            owner_clause = "AND c.owner_email = %s" if owner_email else ""
            params: tuple = (topic_id, owner_email) if owner_email else (topic_id,)
            with self._conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT c.id, c.title,
                           extract(epoch from c.created_at)::bigint AS created,
                           extract(epoch from c.updated_at)::bigint AS updated,
                           (SELECT count(*) FROM messages m
                              WHERE m.conversation_id = c.id) AS message_count
                    FROM conversations c
                    WHERE c.topic_id = %s {owner_clause}
                    ORDER BY c.updated_at DESC
                    """,
                    params,
                )
                return [dict(r) for r in cur.fetchall()]
        except psycopg2.Error as exc:
            log.error("list_conversations(%s) failed: %s", topic_id, exc)
            return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_chat_isolation.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add db/supabase_client.py tests/test_chat_isolation.py
git commit -m "feat(isolation): owner-filtered conversation list + upsert"
```

---

### Task 12: Plumb owner through chat_store

**Files:**
- Modify: `lib/chat_store.py` (`new_thread` ~line 55, `_conv_row` ~line 40, `list_threads` ~line 156)

- [ ] **Step 1: Carry owner on the thread + conv row**

In `new_thread`, add an `owner_email` parameter and field:

```python
def new_thread(run_id: str, title: str = "New chat", *, owner_email: str | None = None) -> dict[str, Any]:
    now = int(time.time())
    return {
        "id": uuid.uuid4().hex[:12],
        "run_id": run_id,
        "topic_id": _topic_id(run_id),
        "owner_email": owner_email,
        "title": title,
        "created": now,
        "updated": now,
        "summary": "",
        "archived_count": 0,
        "messages": [],
    }
```

In `_conv_row`, include the owner:

```python
    return {
        "id": thread["id"],
        "topic_id": thread.get("topic_id") or _topic_id(thread["run_id"]),
        "run_id": thread["run_id"],
        "owner_email": thread.get("owner_email"),
        "title": thread.get("title", "New chat"),
        "summary": thread.get("summary", ""),
        "archived_count": int(thread.get("archived_count", 0)),
    }
```

In `list_threads`, pass the owner to the DB query:

```python
def list_threads(run_id: str, *, owner_email: str | None = None) -> list[dict]:
    pg = _pg()
    if pg and pg.enabled:
        return pg.list_conversations(_topic_id(run_id), owner_email=owner_email)
    chats = store.ROOT / run_id / "chats"
    ...
```

(keep the file-fallback body unchanged below this line.)

- [ ] **Step 2: Verify chat tests still pass**

Run: `.venv/bin/python -m pytest tests/ -k "chat" -v`
Expected: existing chat tests pass (owner is optional, defaults None).

- [ ] **Step 3: Commit**

```bash
git add lib/chat_store.py
git commit -m "feat(isolation): thread owner_email plumbed through chat_store"
```

---

### Task 13: Enforce ownership in server routes

**Files:**
- Modify: `server.py` (`start_run` ~line 208, `start_orchestration_run` ~line 244, `list_runs` route ~line 772, `delete_run_route` ~line 796, `chat_runs` ~line 639, `chat_threads` ~line 674, `chat_thread` ~line 688, `chat_ask` ~line 704, `_disk_runs` ~line 752)

- [ ] **Step 1: Add an owner helper + disk filter**

Add near the top of `server.py` (after the gate definition):

```python
def _owner() -> str | None:
    """The owner to stamp/filter by — None in single-user local mode."""
    return auth_lib.current_user() if auth_lib.auth_active() else None


def _user_owns_run(run_id: str) -> bool:
    owner = _owner()
    if owner is None:
        return True  # local mode: no ownership concept
    from lib.store import get_run_owner
    disk_owner = get_run_owner(run_id)
    if disk_owner is not None:
        return disk_owner == owner
    try:
        from db import get_supabase
        pg = get_supabase()
        if pg.enabled:
            rows = pg.list_runs(owner_email=owner, limit=200) or []
            return any(r["run_id"] == run_id for r in rows)
    except (ImportError, KeyError):
        pass
    return False  # unknown owner under active auth → legacy/hidden
```

- [ ] **Step 2: Stamp owner on run creation**

In `start_run`, right after `run_id = new_run_id()`:

```python
    from lib.store import set_run_owner
    set_run_owner(run_id, _owner())
```

Same two lines after `run_id = new_run_id()` in `start_orchestration_run`.

- [ ] **Step 3: Filter run listings by owner**

In `_disk_runs`, filter by owner. Change its body's append loop guard — after
`if not run: continue` add:

```python
        owner = _owner()
        if owner is not None and get_run_owner(d.name) != owner:
            continue
```

and add `from lib.store import get_run_owner` at the top of `_disk_runs`.

In the `/runs` route and `/chat/runs` route, pass the owner to `pg.list_runs`:
change `pg.list_runs(limit=limit)` → `pg.list_runs(owner_email=_owner(), limit=limit)`
and `pg.list_runs(limit=200)` → `pg.list_runs(owner_email=_owner(), limit=200)`.

In `delete_run_route`, guard before deleting:

```python
    if not _user_owns_run(run_id):
        return jsonify({"error": "not found"}), 404
```

place it right after the `_re.fullmatch` validation. Also pass owner to the DB
delete: `pg.delete_run(run_id)` → `pg.delete_run(run_id, owner_email=_owner())`.

- [ ] **Step 4: Guard chat routes by run ownership + stamp owner**

In `chat_threads` (both GET and POST), after reading `run_id`, add:

```python
    if run_id and not _user_owns_run(run_id):
        return jsonify({"error": "not found"}), 404
```

For the POST branch, stamp owner on creation — change:
`thread = chat_store.new_thread(run_id, title=(data.get("title") or "New chat"))`
→
`thread = chat_store.new_thread(run_id, title=(data.get("title") or "New chat"), owner_email=_owner())`

For the GET branch, pass owner to the listing:
`return jsonify(chat_store.list_threads(run_id))`
→
`return jsonify(chat_store.list_threads(run_id, owner_email=_owner()))`

In `chat_thread(thread_id)`, after reading `run_id`:

```python
    if run_id and not _user_owns_run(run_id):
        return jsonify({"error": "not found"}), 404
```

In `chat_ask`, after `run_id`/`q` validation, add the same guard, and stamp the
owner where a new thread is created — change:
`thread = chat_store.new_thread(run_id, title=q[:48])`
→
`thread = chat_store.new_thread(run_id, title=q[:48], owner_email=_owner())`

- [ ] **Step 5: Verify end-to-end gate + isolation smoke**

Run: `.venv/bin/python -c "
import os
os.environ['SUPABASE_URL']='https://x.supabase.co'; os.environ['SUPABASE_ANON_KEY']='k'
import server
c=server.app.test_client()
with c.session_transaction() as s: s['user_email']='a@x.com'
# a@x.com owns run A
import lib.store as st
rid='testrunZ'; st.set_run_owner(rid,'a@x.com')
print('owns-own', server._user_owns_run.__wrapped__ if hasattr(server._user_owns_run,'__wrapped__') else 'ok')
with server.app.test_request_context():
    pass
print('SMOKE OK')"`
Expected: prints `SMOKE OK` (no exception). Ownership unit behaviour is covered by Task 14.

- [ ] **Step 6: Commit**

```bash
git add server.py
git commit -m "feat(isolation): stamp + enforce per-user ownership on run/chat routes"
```

---

### Task 14: Ownership guard test + full suite

**Files:**
- Test: `tests/test_run_isolation.py` (append)

- [ ] **Step 1: Write the test**

```python
def test_user_owns_run_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("PULSETRACE_DATA_ROOT", str(tmp_path))
    import importlib, lib.store as store
    importlib.reload(store)
    import server
    importlib.reload(server)
    store.set_run_owner("rA", "a@x.com")
    store.set_run_owner("rB", "b@x.com")
    with server.app.test_request_context():
        from flask import session
        monkeypatch.setattr(server.auth_lib, "auth_active", lambda: True)
        session["user_email"] = "a@x.com"
        assert server._user_owns_run("rA") is True
        assert server._user_owns_run("rB") is False
```

- [ ] **Step 2: Run the test**

Run: `.venv/bin/python -m pytest tests/test_run_isolation.py::test_user_owns_run_disk -v`
Expected: 1 passed.

- [ ] **Step 3: Run the full suite (gate off)**

Run: `.venv/bin/python -m pytest -v`
Expected: all pass (no regressions; auth inactive by default in CI/local).

- [ ] **Step 4: Commit**

```bash
git add tests/test_run_isolation.py
git commit -m "test(isolation): per-user run ownership guard"
```

---

### Task 15: Docs + env + CLAUDE.md

**Files:**
- Modify: `.env.example`
- Modify: `CLAUDE.md` (Non-goals section)

- [ ] **Step 1: Document the new env keys**

Append to `.env.example`:

```bash
# --- Authentication (per-user) ---
# When SUPABASE_URL + a key are set, login is enforced and data is per-user.
# Leave unset to run single-user local mode (no login).
FLASK_SECRET_KEY=change-me-to-a-random-string
# SUPABASE_URL / SUPABASE_ANON_KEY are already listed above (reused for auth).
```

- [ ] **Step 2: Update the non-goal line**

In `CLAUDE.md`, change the Non-goals line from:

```
Auth, durable DB, Docker, hosted deployment.
```

to:

```
Durable DB, Docker, hosted deployment. (Per-user auth + isolation added on `feat/authenticate`.)
```

- [ ] **Step 3: Commit**

```bash
git add .env.example CLAUDE.md
git commit -m "docs(auth): env keys + non-goal update for per-user auth"
```

---

## Verification Checklist (run before PR)

- [ ] `.venv/bin/python -m pytest -v` — full suite green.
- [ ] Gate off (no Supabase creds): `/` renders dashboard, no login required.
- [ ] Gate on: `/` → 302 `/login`; `/runs` → 401; `/login` → 200.
- [ ] Manual: sign up → sign in → land on dashboard → run a topic → it appears in history; sign out; sign in as a second user → first user's runs/chats are NOT visible.
- [ ] Google button shows "coming soon", does not error.

## PR

Open PR `feat/authenticate` → `shyan` (per project convention; base is `shyan`, not `main`). Comprehensive body: what/why, the 3 steps, the isolation model, the gate-bypass posture, and the deferred Google OAuth.
