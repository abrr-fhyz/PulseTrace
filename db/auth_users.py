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


def sign_in_with_token(access_token: str) -> AuthResult:
    """Validate an OAuth access token (from a Supabase social login) and return
    the resolved user. Used by the `/auth/callback` bridge after a provider
    redirect; degrades to AuthResult(ok=False) on any failure."""
    if not auth_configured():
        return AuthResult(False, error="Authentication is not configured.")
    if not access_token:
        return AuthResult(False, error="Missing access token.")
    try:
        res = _make_client().auth.get_user(access_token)
        user = getattr(res, "user", None)
        email = getattr(user, "email", None) if user else None
        if not email:
            return AuthResult(False, error="Invalid session token.")
        return AuthResult(True, email=email, access_token=access_token)
    except Exception as exc:  # gotrue/httpx raise varied types; degrade
        log.warning("token sign-in failed: %s", exc)
        return AuthResult(False, error=str(exc) or "Invalid session token.")


def reset_password(email: str) -> AuthResult:
    if not auth_configured():
        return AuthResult(False, error="Authentication is not configured.")
    try:
        _make_client().auth.reset_password_for_email(email)
        return AuthResult(True, email=email, message="Reset link sent if the account exists.")
    except Exception as exc:
        log.warning("reset_password failed for %s: %s", email, exc)
        return AuthResult(False, error=str(exc) or "Could not send a reset link.")
