"""JWT handling and on-disk session storage.

Beli uses SimpleJWT: ``POST /api/token/`` returns an access token (about 20
minutes) and a refresh token (about 7 days, not rotated on refresh).
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .errors import AuthenticationError


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
