"""Authenticated Supabase REST client (PostgREST via supabase-py).

The hot-path data layer in `supabase_client.py` connects to Postgres directly
as the `postgres` role, which *bypasses* Row Level Security. This module is the
complementary channel: it signs a real Supabase Auth user (the dev account) in
with email/password, so REST calls run as the `authenticated` role and are
governed by your RLS policies.

It is *additive* and fail-safe, like the rest of `db/`: when the URL, key, or
dev-account credentials are absent (or `supabase-py` isn't installed) the
instance reports `enabled is False` and exposes no client — callers fall back to
the direct-Postgres path. A failed sign-in degrades to disabled, never raises
into the agent loop.

Env (first hit wins):
    URL   : SUPABASE_URL > SUPABASE_PROJECT_URL
    KEY   : SUPABASE_PUBLISHABLE_KEY > SUPABASE_ANON_KEY > SUPABASE_KEY
    USER  : SUPABASE_AUTH_EMAIL / SUPABASE_AUTH_PASSWORD
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("pulsetrace.db.supabase_auth")

try:  # heavy optional dep — mirrors psycopg2 handling in supabase_client.py
    from supabase import Client, create_client
    _HAVE_SUPABASE = True
except ImportError:  # pragma: no cover - exercised only when dep missing
    _HAVE_SUPABASE = False


def _resolve_url() -> str:
    return os.environ.get("SUPABASE_URL") or os.environ.get("SUPABASE_PROJECT_URL", "")


def _resolve_key() -> str:
    for name in ("SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY", "SUPABASE_KEY"):
        val = os.environ.get(name)
        if val:
            return val
    return ""


class SupabaseAuthClient:
    """Signed-in Supabase REST client scoped to the dev account."""

    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
        *,
        email: str | None = None,
        password: str | None = None,
    ) -> None:
        self._url = url or _resolve_url()
        self._key = key or _resolve_key()
        self._email = email if email is not None else os.environ.get("SUPABASE_AUTH_EMAIL", "")
        self._password = (
            password if password is not None else os.environ.get("SUPABASE_AUTH_PASSWORD", "")
        )
        self._client: "Client | None" = None
        self.user: object | None = None

        self.enabled = bool(
            self._url and self._key and self._email and self._password
        ) and _HAVE_SUPABASE
        if (self._url and self._key) and not _HAVE_SUPABASE:
            log.warning("SUPABASE_URL/key set but supabase-py not installed; REST auth disabled.")
        if self.enabled:
            self._sign_in()

    def _sign_in(self) -> None:
        try:
            client = create_client(self._url, self._key)
            res = client.auth.sign_in_with_password(
                {"email": self._email, "password": self._password}
            )
            self._client = client
            self.user = res.user
        except Exception as exc:  # gotrue/httpx raise many types across versions; degrade, don't crash
            log.error("Supabase sign-in failed for %s: %s", self._email, exc)
            self.enabled = False
            self._client = None
            self.user = None

    @property
    def client(self) -> "Client":
        if not self.enabled or self._client is None:
            raise RuntimeError("SupabaseAuthClient is not enabled (missing creds or failed sign-in)")
        return self._client

    def ensure_session(self) -> bool:
        """Re-authenticate if the session was lost. Returns True when usable.

        supabase-py auto-refreshes a live access token; this only recovers the
        case where the session is gone entirely (process idle past refresh)."""
        if not self.enabled or self._client is None:
            return False
        try:
            if self._client.auth.get_session() is not None:
                return True
        except Exception as exc:  # session probe failure → attempt fresh sign-in
            log.warning("session probe failed: %s; re-signing in.", exc)
        self._sign_in()
        return self.enabled

    def table(self, name: str):
        """Proxy to the authenticated PostgREST table builder."""
        return self.client.table(name)

    def health(self) -> dict:
        if not self.enabled or self.user is None:
            return {"enabled": False, "backend": "rest-auth"}
        uid = getattr(self.user, "id", None)
        email = getattr(self.user, "email", None)
        return {"enabled": True, "backend": "rest-auth", "user_id": uid, "email": email}
