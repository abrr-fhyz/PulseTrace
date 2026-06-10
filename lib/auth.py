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
