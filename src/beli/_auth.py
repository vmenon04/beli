"""Tokens, the session file, and where credentials come from.

Beli uses SimpleJWT: ``POST /api/token/`` returns an access token (about 20
minutes) and a refresh token (about 7 days, not rotated on refresh).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .errors import AuthenticationError

log = logging.getLogger("beli")


def decode_claims(token: str) -> dict[str, Any]:
    """Return a JWT's payload without verifying the signature."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError) as exc:
        raise AuthenticationError("Not a valid JWT") from exc
    if not isinstance(claims, dict):
        raise AuthenticationError("Not a valid JWT")
    return claims


def is_expired(token: str | None, skew: float = 60.0) -> bool:
    """True if the token is missing, unreadable or within ``skew`` seconds of expiry."""
    if not token:
        return True
    try:
        return float(decode_claims(token)["exp"]) - skew <= time.time()
    except (AuthenticationError, KeyError, TypeError, ValueError):
        return True


@dataclass
class Tokens:
    access: str = ""
    refresh: str = ""

    @property
    def user_id(self) -> str:
        for token in (self.access, self.refresh):
            if token:
                user_id = decode_claims(token).get("user_id")
                if user_id:
                    return str(user_id)
        raise AuthenticationError("No token carries a user_id")


def default_session_path() -> Path:
    """``$BELI_SESSION_FILE``, else ``$XDG_CONFIG_HOME/beli/session.json``."""
    if env := os.environ.get("BELI_SESSION_FILE"):
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "beli" / "session.json"


def load_tokens(path: Path) -> Tokens | None:
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return None
    return Tokens(access=data.get("access", ""), refresh=data.get("refresh", ""))


def save_tokens(path: Path, tokens: Tokens) -> None:
    """Write tokens with owner-only permissions. Passwords are never stored."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(asdict(tokens), fh)
    os.replace(tmp, path)


@dataclass(frozen=True)
class Credentials:
    """What a client was given to authenticate with, and where it came from."""

    source: str
    email: str | None = None
    phone: str | None = None
    password: str | None = None
    tokens: Tokens = field(default_factory=Tokens)

    def login_body(self) -> dict[str, str]:
        """The body for ``POST /api/token/``. Raises if there is no password to log in with."""
        if not self.password or not (self.email or self.phone):
            raise AuthenticationError(
                f"No usable session (credentials came from {self.source}). Pass email (or "
                "phone) and password, a refresh_token, or run `beli login`."
            )
        if self.email:
            return {"password": self.password, "email": self.email}
        return {"password": self.password, "phone_no": self.phone or ""}


def find_credentials(
    *,
    email: str | None = None,
    phone: str | None = None,
    password: str | None = None,
    access_token: str | None = None,
    refresh_token: str | None = None,
    session_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Credentials:
    """Choose where credentials come from. The first source that has any wins outright.

    1. Constructor arguments, if any credential argument was passed.
    2. The session file, if one was named and it holds a token that has not expired.
    3. The environment: ``BELI_REFRESH_TOKEN``, or ``BELI_PASSWORD`` with
       ``BELI_EMAIL`` or ``BELI_PHONE``.

    Sources are never mixed: an email argument is not completed with
    ``BELI_PASSWORD``, and a session file is not backed up by a password from
    the environment.
    """
    found = _find(email, phone, password, access_token, refresh_token, session_file, environ)
    log.debug("credentials: using %s", found.source)
    return found


def _find(
    email: str | None,
    phone: str | None,
    password: str | None,
    access_token: str | None,
    refresh_token: str | None,
    session_file: Path | None,
    environ: Mapping[str, str] | None,
) -> Credentials:
    if email or phone or password or access_token or refresh_token:
        tokens = Tokens(access=access_token or "", refresh=refresh_token or "")
        return Credentials(
            "constructor arguments", email or None, phone or None, password or None, tokens
        )

    if session_file is not None:
        stored = load_tokens(session_file)
        if stored is None:
            log.debug("credentials: no session file at %s", session_file)
        elif is_expired(stored.refresh, skew=0) and is_expired(stored.access):
            log.debug("credentials: the session in %s has expired", session_file)
        else:
            return Credentials(f"session file {session_file}", tokens=stored)

    env = os.environ if environ is None else environ
    env_email = env.get("BELI_EMAIL") or None
    env_phone = env.get("BELI_PHONE") or None
    env_password = env.get("BELI_PASSWORD") or None
    env_refresh = env.get("BELI_REFRESH_TOKEN", "")
    if env_refresh or (env_password and (env_email or env_phone)):
        return Credentials(
            "environment variables", env_email, env_phone, env_password, Tokens(refresh=env_refresh)
        )
    return Credentials("nothing")
