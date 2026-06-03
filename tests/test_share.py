from __future__ import annotations

import json
import tarfile

from lib import share, store


SECRET = "test-secret-value"


def test_token_round_trip_valid():
    token = share.make_token("run-123", expires_at=1000, secret=SECRET)
    assert share.verify_token(token, SECRET, now=500) == "run-123"


def test_token_expired_returns_none():
    token = share.make_token("run-123", expires_at=1000, secret=SECRET)
    assert share.verify_token(token, SECRET, now=1001) is None


def test_token_at_exact_expiry_is_invalid():
    token = share.make_token("run-123", expires_at=1000, secret=SECRET)
    assert share.verify_token(token, SECRET, now=1000) is None


def test_tampered_payload_returns_none():
    token = share.make_token("run-123", expires_at=1000, secret=SECRET)
    payload, sig = token.split(".", 1)
    # Flip a character in the payload so the signature no longer matches.
    bad_payload = ("A" if payload[0] != "A" else "B") + payload[1:]
    assert share.verify_token(f"{bad_payload}.{sig}", SECRET, now=500) is None


def test_tampered_signature_returns_none():
    token = share.make_token("run-123", expires_at=1000, secret=SECRET)
    payload, sig = token.split(".", 1)
    bad_sig = ("A" if sig[0] != "A" else "B") + sig[1:]
    assert share.verify_token(f"{payload}.{bad_sig}", SECRET, now=500) is None


def test_wrong_secret_returns_none():
    token = share.make_token("run-123", expires_at=1000, secret=SECRET)
    assert share.verify_token(token, "other-secret", now=500) is None


def test_malformed_tokens_return_none():
    assert share.verify_token("", SECRET, now=500) is None
    assert share.verify_token("no-dot-here", SECRET, now=500) is None
    assert share.verify_token("not-base64!!.sig", SECRET, now=500) is None
    assert share.verify_token("....", SECRET, now=500) is None


def test_bundle_creates_readable_tarball(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    run_id = "run-abc"
    d = store.run_dir(run_id)
    (d / "run.json").write_text(json.dumps({"id": run_id, "topic": "demo"}))
    (d / "posts.json").write_text(json.dumps([{"id": "p1"}]))
    (d / "shots").mkdir()
    (d / "shots" / "a.txt").write_text("hello")

    dest = tmp_path / "out"
    dest.mkdir()
    path = share.bundle_run(run_id, dest_dir=str(dest))

    assert path == str(dest / f"pulsetrace-{run_id}.tar.gz")
    with tarfile.open(path, "r:gz") as tf:
        names = set(tf.getnames())
    assert f"{run_id}/run.json" in names
    assert f"{run_id}/posts.json" in names
    assert f"{run_id}/shots/a.txt" in names


def test_bundle_missing_run_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    import pytest

    with pytest.raises(FileNotFoundError):
        share.bundle_run("does-not-exist", dest_dir=str(tmp_path))
