"""Credential precedence: constructor arguments, then session file, then environment."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
import respx

from beli import AuthenticationError, Beli
from beli._auth import Tokens, find_credentials, save_tokens

from .conftest import make_jwt

ENV = {"BELI_EMAIL": "env@example.com", "BELI_PASSWORD": "env-pw"}


@pytest.fixture
def session(tmp_path: Path) -> Path:
    path = tmp_path / "session.json"
    save_tokens(path, Tokens(access=make_jwt(), refresh=make_jwt(3600, kind="refresh")))
    return path


def test_constructor_beats_session_file_and_environment(session: Path) -> None:
    found = find_credentials(
        email="arg@example.com", password="arg-pw", session_file=session, environ=ENV
    )
    assert found.source == "constructor arguments"
    assert (found.email, found.password, found.tokens) == ("arg@example.com", "arg-pw", Tokens())


def test_session_file_beats_environment(session: Path) -> None:
    env = {**ENV, "BELI_REFRESH_TOKEN": make_jwt(3600, kind="refresh")}
    found = find_credentials(session_file=session, environ=env)
    assert found.source == f"session file {session}"
    assert found.tokens.refresh == json.loads(session.read_text())["refresh"]
    assert found.password is None  # not topped up from the environment


def test_environment_is_last(tmp_path: Path) -> None:
    found = find_credentials(session_file=tmp_path / "missing.json", environ=ENV)
    assert (found.source, found.email, found.password) == (
        "environment variables",
        "env@example.com",
        "env-pw",
    )
    token = make_jwt(3600, kind="refresh")
    assert find_credentials(environ={"BELI_REFRESH_TOKEN": token}).tokens.refresh == token
    assert find_credentials(environ={"BELI_PHONE": "+1555", "BELI_PASSWORD": "x"}).phone == "+1555"


def test_expired_session_file_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    save_tokens(path, Tokens(access=make_jwt(-100), refresh=make_jwt(-10, kind="refresh")))
    assert find_credentials(session_file=path, environ=ENV).source == "environment variables"
    assert find_credentials(session_file=path, environ={}).source == "nothing"


def test_sources_are_not_mixed() -> None:
    # An email argument makes the constructor the source; BELI_PASSWORD does not complete it.
    found = find_credentials(email="arg@example.com", environ=ENV)
    assert (found.source, found.password) == ("constructor arguments", None)
    # Half a login in the environment is not a credential.
    assert find_credentials(environ={"BELI_EMAIL": "env@example.com"}).source == "nothing"
    assert find_credentials(environ={"BELI_PASSWORD": "pw"}).source == "nothing"


def test_incomplete_constructor_credentials_fail_and_say_where_from(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BELI_PASSWORD", "env-pw")
    with pytest.raises(AuthenticationError, match="came from constructor arguments"):
        Beli(email="arg@example.com", min_interval=0).me()


def test_client_uses_session_file_then_environment(
    api: respx.MockRouter, session: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BELI_EMAIL", "env@example.com")
    monkeypatch.setenv("BELI_PASSWORD", "env-pw")
    Beli.from_session(session, min_interval=0).me()
    assert [c.request.url.path for c in api.calls] == ["/api/user/logged-in/"]

    session.unlink()
    Beli.from_session(session, min_interval=0).me()
    login = api.calls[1].request
    assert login.url.path == "/api/token/"
    assert json.loads(login.content) == {"email": "env@example.com", "password": "env-pw"}
    assert session.exists()  # tokens from the environment login are saved for next time


def test_source_is_logged_at_debug_without_secrets(
    session: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="beli")
    monkeypatch.setenv("BELI_EMAIL", "env@example.com")
    monkeypatch.setenv("BELI_PASSWORD", "env-pw")
    Beli("arg@example.com", "arg-pw")
    Beli.from_session(session)
    Beli()
    assert [r.getMessage() for r in caplog.records] == [
        "credentials: using constructor arguments",
        f"credentials: using session file {session}",
        "credentials: using environment variables",
    ]
    assert all(r.levelno == logging.DEBUG for r in caplog.records)
    stored = json.loads(session.read_text())
    for secret in ("arg-pw", "env-pw", "arg@example.com", stored["access"], stored["refresh"]):
        assert secret not in caplog.text
