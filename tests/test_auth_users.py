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
    with patch.object(auth_users, "_make_client", return_value=_fake_client()), \
         patch.object(auth_users, "auth_configured", return_value=True):
        r = auth_users.sign_in("u@x.com", "pw")
    assert r.ok is True and r.email == "u@x.com" and r.access_token == "tok" and r.error is None


def test_sign_in_failure_degrades():
    with patch.object(auth_users, "_make_client", return_value=_fake_client(raises=ValueError("bad creds"))), \
         patch.object(auth_users, "auth_configured", return_value=True):
        r = auth_users.sign_in("u@x.com", "wrong")
    assert r.ok is False and r.email is None and "bad creds" in (r.error or "")


def test_sign_up_success():
    with patch.object(auth_users, "_make_client", return_value=_fake_client()), \
         patch.object(auth_users, "auth_configured", return_value=True):
        r = auth_users.sign_up("u@x.com", "pw123456")
    assert r.ok is True and r.email == "u@x.com"


def test_auth_configured_false_without_env(monkeypatch):
    for k in ("SUPABASE_URL", "SUPABASE_PROJECT_URL", "SUPABASE_PUBLISHABLE_KEY",
              "SUPABASE_ANON_KEY", "SUPABASE_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert auth_users.auth_configured() is False
