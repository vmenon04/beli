"""HTTP plumbing shared by the sync and async clients.

Every endpoint is described once as a :class:`Request`. The sync and async
transports differ only in how they wait and do I/O.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Generic, TypeVar

import httpx

from ._auth import Tokens, is_expired, save_tokens
from ._constants import DEFAULT_USER_AGENT, HOST_API, HOST_ONBOARD, ORIGIN
from .errors import AuthenticationError, error_for

T = TypeVar("T")

ME = "__BELI_ME__"
"""Stand-in for the logged-in user's id. Resolved after authentication."""

RETRY_STATUSES = frozenset({429, 502, 503, 504})


def _check_read_only(request: Request[Any]) -> None:
    """Only login and token refresh may POST. Everything sent with your token is a GET."""
    if request.auth and request.method != "GET":
        raise ValueError(f"beli is read-only; refusing {request.method} {request.path}")


def _identity(data: Any) -> Any:
    return data


@dataclass(frozen=True)
class Request(Generic[T]):
    method: str
    path: str
    params: Mapping[str, Any] | None = None
    json: Any = None
    host: str = HOST_API
    parse: Callable[[Any], T] = field(default=_identity)
    auth: bool = True

    def resolve(self, user_id: str | None) -> Request[T]:
        if user_id is None:
            return self

        def sub(value: Any) -> Any:
            if isinstance(value, str):
                return value.replace(ME, user_id)
            if isinstance(value, Mapping):
                return {k: sub(v) for k, v in value.items()}
            if isinstance(value, list):
                return [sub(v) for v in value]
            return value

        return replace(
            self,
            path=sub(self.path),
            params=sub(self.params) if self.params is not None else None,
            json=sub(self.json),
        )

    @property
    def needs_user(self) -> bool:
        return ME in repr((self.path, self.params, self.json))


@dataclass
class Config:
    email: str | None = None
    phone: str | None = None
    password: str | None = None
    tokens: Tokens = field(default_factory=Tokens)
    session_file: Path | None = None
    min_interval: float = 1.0
    max_retries: int = 4
    timeout: float = 30.0
    user_agent: str = DEFAULT_USER_AGENT

    @classmethod
    def build(
        cls,
        *,
        email: str | None,
        phone: str | None,
        password: str | None,
        access_token: str | None,
        refresh_token: str | None,
        session_file: str | os.PathLike[str] | None,
        min_interval: float,
        max_retries: int,
        timeout: float,
        user_agent: str | None,
    ) -> Config:
        from ._auth import load_tokens

        path = Path(session_file).expanduser() if session_file is not None else None
        tokens = Tokens(access=access_token or "", refresh=refresh_token or "")
        if not (tokens.access or tokens.refresh):
            env_refresh = os.environ.get("BELI_REFRESH_TOKEN", "")
            stored = load_tokens(path) if path else None
            if env_refresh:
                tokens = Tokens(refresh=env_refresh)
            elif stored:
                tokens = stored
        return cls(
            email=email or os.environ.get("BELI_EMAIL") or None,
            phone=phone or os.environ.get("BELI_PHONE") or None,
            password=password or os.environ.get("BELI_PASSWORD") or None,
            tokens=tokens,
            session_file=path,
            min_interval=min_interval,
            max_retries=max_retries,
            timeout=timeout,
            user_agent=user_agent or DEFAULT_USER_AGENT,
        )

    def headers(self) -> dict[str, str]:
        return {
            "Origin": ORIGIN,
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }

    def login_body(self) -> dict[str, str]:
        if not self.password or not (self.email or self.phone):
            raise AuthenticationError(
                "No usable session. Pass email (or phone) and password, a refresh_token, "
                "or run `beli login`."
            )
        body = {"password": self.password}
        if self.email:
            body["email"] = self.email
        else:
            body["phone_no"] = self.phone or ""
        return body

    def store(self) -> None:
        if self.session_file is not None:
            save_tokens(self.session_file, self.tokens)


def retry_delay(response: httpx.Response | None, attempt: int) -> float:
    if response is not None and (header := response.headers.get("Retry-After")):
        try:
            return min(float(header), 120.0)
        except ValueError:
            try:
                return max(0.0, float(parsedate_to_datetime(header).timestamp()) - time.time())
            except (TypeError, ValueError):
                pass
    return min(2.0 * 2.0**attempt, 60.0)


def decode(response: httpx.Response) -> Any:
    """Parse a body. Some writes return 200 with an empty body."""
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text


def _auth_failure(response: httpx.Response, what: str) -> AuthenticationError:
    detail = decode(response)
    if isinstance(detail, dict):
        detail = detail.get("detail", detail)
    return AuthenticationError(f"{what} failed (HTTP {response.status_code}): {detail}")


class SyncTransport:
    def __init__(self, config: Config, http: httpx.Client | None = None) -> None:
        self.config = config
        self._owns_http = http is None
        self.http = http or httpx.Client(timeout=config.timeout)
        self._lock = threading.Lock()
        self._last = 0.0

    def close(self) -> None:
        if self._owns_http:
            self.http.close()

    def _throttle(self) -> None:
        with self._lock:
            wait = self.config.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def _post_auth(self, path: str, body: dict[str, str]) -> httpx.Response:
        self._throttle()
        return self.http.post(HOST_ONBOARD + path, json=body, headers=self.config.headers())

    def login(self) -> Tokens:
        response = self._post_auth("/api/token/", self.config.login_body())
        if response.status_code != 200:
            raise _auth_failure(response, "Login")
        data = response.json()
        self.config.tokens = Tokens(access=data["access"], refresh=data["refresh"])
        self.config.store()
        return self.config.tokens

    def access_token(self, *, force: bool = False) -> str:
        tokens = self.config.tokens
        if not force and not is_expired(tokens.access):
            return tokens.access
        if not is_expired(tokens.refresh, skew=0):
            response = self._post_auth("/api/token/refresh/", {"refresh": tokens.refresh})
            if response.status_code == 200:
                tokens.access = response.json()["access"]
                if new_refresh := response.json().get("refresh"):
                    tokens.refresh = new_refresh
                self.config.store()
                return tokens.access
        return self.login().access

    def user_id(self) -> str:
        self.access_token()
        return self.config.tokens.user_id

    def send(self, request: Request[T]) -> T:
        _check_read_only(request)
        if request.auth and request.needs_user:
            request = request.resolve(self.user_id())
        reauthed = False
        attempt = 0
        while True:
            headers = self.config.headers()
            if request.auth:
                headers["Authorization"] = f"Bearer {self.access_token()}"
            self._throttle()
            try:
                response = self.http.request(
                    request.method,
                    request.host + request.path,
                    params=request.params,
                    json=request.json,
                    headers=headers,
                )
            except httpx.TransportError:
                if attempt >= self.config.max_retries:
                    raise
                time.sleep(retry_delay(None, attempt))
                attempt += 1
                continue
            if response.status_code == 401 and request.auth and not reauthed:
                reauthed = True
                self.access_token(force=True)
                continue
            if response.status_code in RETRY_STATUSES and attempt < self.config.max_retries:
                time.sleep(retry_delay(response, attempt))
                attempt += 1
                continue
            if response.status_code >= 400:
                raise error_for(response)
            return request.parse(decode(response))


class AsyncTransport:
    def __init__(self, config: Config, http: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._owns_http = http is None
        self.http = http or httpx.AsyncClient(timeout=config.timeout)
        self._throttle_lock = asyncio.Lock()
        self._auth_lock = asyncio.Lock()
        self._last = 0.0

    async def close(self) -> None:
        if self._owns_http:
            await self.http.aclose()

    async def _throttle(self) -> None:
        async with self._throttle_lock:
            wait = self.config.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()

    async def _post_auth(self, path: str, body: dict[str, str]) -> httpx.Response:
        await self._throttle()
        return await self.http.post(HOST_ONBOARD + path, json=body, headers=self.config.headers())

    async def login(self) -> Tokens:
        response = await self._post_auth("/api/token/", self.config.login_body())
        if response.status_code != 200:
            raise _auth_failure(response, "Login")
        data = response.json()
        self.config.tokens = Tokens(access=data["access"], refresh=data["refresh"])
        self.config.store()
        return self.config.tokens

    async def access_token(self, *, force: bool = False) -> str:
        async with self._auth_lock:
            tokens = self.config.tokens
            if not force and not is_expired(tokens.access):
                return tokens.access
            if not is_expired(tokens.refresh, skew=0):
                response = await self._post_auth("/api/token/refresh/", {"refresh": tokens.refresh})
                if response.status_code == 200:
                    tokens.access = response.json()["access"]
                    if new_refresh := response.json().get("refresh"):
                        tokens.refresh = new_refresh
                    self.config.store()
                    return tokens.access
            return (await self.login()).access

    async def user_id(self) -> str:
        await self.access_token()
        return self.config.tokens.user_id

    async def send(self, request: Request[T]) -> T:
        _check_read_only(request)
        if request.auth and request.needs_user:
            request = request.resolve(await self.user_id())
        reauthed = False
        attempt = 0
        while True:
            headers = self.config.headers()
            if request.auth:
                headers["Authorization"] = f"Bearer {await self.access_token()}"
            await self._throttle()
            try:
                response = await self.http.request(
                    request.method,
                    request.host + request.path,
                    params=request.params,
                    json=request.json,
                    headers=headers,
                )
            except httpx.TransportError:
                if attempt >= self.config.max_retries:
                    raise
                await asyncio.sleep(retry_delay(None, attempt))
                attempt += 1
                continue
            if response.status_code == 401 and request.auth and not reauthed:
                reauthed = True
                await self.access_token(force=True)
                continue
            if response.status_code in RETRY_STATUSES and attempt < self.config.max_retries:
                await asyncio.sleep(retry_delay(response, attempt))
                attempt += 1
                continue
            if response.status_code >= 400:
                raise error_for(response)
            return request.parse(decode(response))
