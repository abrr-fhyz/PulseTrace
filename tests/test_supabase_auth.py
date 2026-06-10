from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from db.supabase_auth import SupabaseAuthClient

ENV = {
    "SUPABASE_URL": "https://ref.supabase.co",
    "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_x",
    "SUPABASE_AUTH_EMAIL": "dev@example.com",
    "SUPABASE_AUTH_PASSWORD": "secret",
}


def _mock_client(user_id: str = "uid-1", email: str = "dev@example.com") -> MagicMock:
    client = MagicMock()
    user = MagicMock(id=user_id, email=email)
    client.auth.sign_in_with_password.return_value = MagicMock(user=user)
    return client


def test_disabled_when_credentials_missing():
    with patch.dict(os.environ, {}, clear=True):
        c = SupabaseAuthClient()
    assert c.enabled is False
    with pytest.raises(RuntimeError):
        _ = c.client


def test_disabled_when_password_absent():
    partial = {k: v for k, v in ENV.items() if k != "SUPABASE_AUTH_PASSWORD"}
    with patch.dict(os.environ, partial, clear=True):
        c = SupabaseAuthClient()
    assert c.enabled is False


def test_signs_in_with_dev_account_and_enables():
    fake = _mock_client()
    with patch.dict(os.environ, ENV, clear=True), \
         patch("db.supabase_auth._HAVE_SUPABASE", True), \
         patch("db.supabase_auth.create_client", return_value=fake) as cc:
        c = SupabaseAuthClient()

    cc.assert_called_once_with("https://ref.supabase.co", "sb_publishable_x")
    fake.auth.sign_in_with_password.assert_called_once_with(
        {"email": "dev@example.com", "password": "secret"}
    )
    assert c.enabled is True
    assert c.client is fake
    assert c.health() == {
        "enabled": True, "backend": "rest-auth", "user_id": "uid-1", "email": "dev@example.com",
    }


def test_table_proxies_to_authenticated_client():
    fake = _mock_client()
    with patch.dict(os.environ, ENV, clear=True), \
         patch("db.supabase_auth._HAVE_SUPABASE", True), \
         patch("db.supabase_auth.create_client", return_value=fake):
        c = SupabaseAuthClient()
    c.table("runs")
    fake.table.assert_called_once_with("runs")


def test_sign_in_failure_degrades_to_disabled():
    fake = MagicMock()
    fake.auth.sign_in_with_password.side_effect = RuntimeError("bad creds")
    with patch.dict(os.environ, ENV, clear=True), \
         patch("db.supabase_auth._HAVE_SUPABASE", True), \
         patch("db.supabase_auth.create_client", return_value=fake):
        c = SupabaseAuthClient()
    assert c.enabled is False
    assert c.health()["enabled"] is False


def test_explicit_args_override_env():
    fake = _mock_client(email="other@example.com")
    with patch.dict(os.environ, {}, clear=True), \
         patch("db.supabase_auth._HAVE_SUPABASE", True), \
         patch("db.supabase_auth.create_client", return_value=fake):
        c = SupabaseAuthClient(
            "https://u.supabase.co", "k", email="other@example.com", password="pw"
        )
    assert c.enabled is True
    fake.auth.sign_in_with_password.assert_called_once_with(
        {"email": "other@example.com", "password": "pw"}
    )


def test_singleton_returns_same_instance():
    import db
    db._supabase_auth = None
    with patch.dict(os.environ, {}, clear=True):
        a = db.get_supabase_auth()
        b = db.get_supabase_auth()
    assert a is b
    db._supabase_auth = None


@pytest.mark.skipif(
    os.environ.get("SUPABASE_AUTH_LIVE") != "1",
    reason="live Supabase auth test; set SUPABASE_AUTH_LIVE=1 to run",
)
def test_live_sign_in_and_read():
    c = SupabaseAuthClient()
    assert c.enabled is True, "live creds must be in .env"
    rows = c.table("runs").select("run_id").limit(1).execute()
    assert hasattr(rows, "data")
