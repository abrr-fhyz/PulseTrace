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
