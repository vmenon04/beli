"""Everything the clients do, with the I/O left out.

Nothing in this module sleeps, takes a lock or touches the network. A
:class:`Session` describes the work as generators ("flows") that yield
effects and receive their results:

* :class:`Call` asks for one HTTP exchange and gets back an
  ``httpx.Response``, or the ``httpx.TransportError`` if it never completed.
* :class:`Sleep` asks to wait.
* :class:`Exclusive` asks for another flow to be run while holding the
  transport's auth lock, and gets back that flow's return value.

``_transport`` has the two small loops that carry the effects out, one
blocking and one with ``await``. Login, token refresh, retries and the
read-only guard therefore exist once, and the sync and async clients cannot
behave differently.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Generic, TypeVar

import httpx

from ._auth import Tokens, is_expired, load_tokens, save_tokens
from ._constants import (
    DEFAULT_USER_AGENT,
    DISCOVERED_HOSTS,
    FALLBACK_HOSTS,
    HOSTS_PATH,
    ORIGIN,
)
from .errors import APIError, AuthenticationError, error_for

T = TypeVar("T")

log = logging.getLogger("beli")

RETRY_STATUSES = frozenset({429, 502, 503, 504})

AUTH_PATHS = frozenset({"/api/token/", "/api/token/refresh/"})
"""The only paths that may be sent anything other than a GET."""


def _identity(data: Any) -> Any:
    return data


@dataclass(frozen=True)
class Request(Generic[T]):
    """One read of the API: where to GET and how to parse the answer.

    ``host`` is a service name (``"api"``, ``"onboard"`` or ``"recs"``), which
    the session maps to a base URL, or a full base URL to use as given.
    """

    method: str
    path: str
    params: Mapping[str, Any] | None = None
    host: str = "api"
    parse: Callable[[Any], T] = field(default=_identity)


@dataclass(frozen=True)
class Call:
    """Effect: perform one HTTP exchange.

    This is the read-only guard. Every request either client sends is a
    ``Call``, and one that is not a GET, or a POST to login or token refresh,
    cannot be constructed.
    """

    method: str
    url: str
    params: Mapping[str, Any] | None = None
    json: Any = None
    headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        path = httpx.URL(self.url).path
        if self.method == "GET" and self.json is None:
            return
        if self.method == "POST" and path in AUTH_PATHS:
            return
        raise ValueError(f"beli is read-only; refusing {self.method} {path}")


@dataclass(frozen=True)
class Sleep:
    """Effect: wait this many seconds."""

    seconds: float


@dataclass(frozen=True)
class Exclusive:
    """Effect: run ``flow`` while holding the auth lock and reply with its result."""

    flow: Generator[Any, Any, Any]


Effect = Call | Sleep | Exclusive
Flow = Generator[Effect, Any, T]
"""A unit of work for a transport to carry out. Returns ``T`` when exhausted."""

Plan = Generator[Request[Any], Any, T]
"""Several requests in a row: yields each one and receives its parsed result.

An :class:`~beli.errors.APIError` from a request is thrown into the plan at
the ``yield``, so a plan can decide that a part is optional.
"""


@dataclass(frozen=True)
class Credentials:
    source: str
    email: str | None = None
    phone: str | None = None
    password: str | None = None
    tokens: Tokens = field(default_factory=Tokens)


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
    the environment. The session file is still where new tokens are saved,
    whichever source they came from.
    """
    env = os.environ if environ is None else environ
    if email or phone or password or access_token or refresh_token:
        return Credentials(
            "constructor arguments",
            email or None,
            phone or None,
            password or None,
            Tokens(access=access_token or "", refresh=refresh_token or ""),
        )
    if session_file is not None:
        stored = load_tokens(session_file)
        if stored is None:
            log.debug("credentials: no session file at %s", session_file)
        elif is_expired(stored.refresh, skew=0) and is_expired(stored.access):
            log.debug("credentials: the session in %s has expired", session_file)
        else:
            return Credentials(f"session file {session_file}", tokens=stored)
    env_email, env_phone = env.get("BELI_EMAIL") or None, env.get("BELI_PHONE") or None
    env_password, env_refresh = env.get("BELI_PASSWORD") or None, env.get("BELI_REFRESH_TOKEN", "")
    if env_refresh or (env_password and (env_email or env_phone)):
        return Credentials(
            "environment variables", env_email, env_phone, env_password, Tokens(refresh=env_refresh)
        )
    return Credentials("nothing")


@dataclass
class Config:
    email: str | None = None
    phone: str | None = None
    password: str | None = None
    tokens: Tokens = field(default_factory=Tokens)
    session_file: Path | None = None
    source: str = "nothing"
    min_interval: float = 1.0
    max_retries: int = 4
    timeout: float = 30.0
    user_agent: str = DEFAULT_USER_AGENT
    discover_hosts: bool = True

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
        discover_hosts: bool = True,
    ) -> Config:
        path = Path(session_file).expanduser() if session_file is not None else None
        found = find_credentials(
            email=email,
            phone=phone,
            password=password,
            access_token=access_token,
            refresh_token=refresh_token,
            session_file=path,
        )
        log.debug("credentials: using %s", found.source)
        return cls(
            email=found.email,
            phone=found.phone,
            password=found.password,
            tokens=found.tokens,
            session_file=path,
            source=found.source,
            min_interval=min_interval,
            max_retries=max_retries,
            timeout=timeout,
            user_agent=user_agent or DEFAULT_USER_AGENT,
            discover_hosts=discover_hosts,
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
                f"No usable session (credentials came from {self.source}). Pass email (or "
                "phone) and password, a refresh_token, or run `beli login`."
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
    """Parse a body. Some endpoints answer 200 with an empty body."""
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


_HOST = re.compile(r"(?:https://)?([A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::\d+)?)/?")


def parse_hosts(data: Any) -> dict[str, str]:
    """Pick the base URLs this package uses out of an api-hosts response.

    Tokens are sent to whatever this returns, so a value is used only if it is
    a bare host name or an ``https://`` origin with no path. Anything else is
    skipped and the hard-coded host stays in place.
    """
    found: dict[str, str] = {}
    if not isinstance(data, dict):
        return found
    for key, service in DISCOVERED_HOSTS.items():
        value = data.get(key)
        if not isinstance(value, str):
            continue
        match = _HOST.fullmatch(value.strip())
        if match:
            found[service] = "https://" + match.group(1)
    return found


class Session:
    """Auth state and request logic for one client, as flows."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._user_id: str | None = None
        self.hosts = dict(FALLBACK_HOSTS)
        self._hosts_known = not config.discover_hosts

    # Flows the transports expose

    def login(self) -> Flow[Tokens]:
        """Log in with the password now, replacing any tokens held."""
        tokens: Tokens = yield Exclusive(self._login())
        return tokens

    def access_token(self, *, rejected: str | None = None) -> Flow[str]:
        """A usable access token, refreshing or logging in if needed.

        ``rejected`` is a token the API just answered 401 to. It is replaced
        even if it has not expired, unless another caller already replaced it.
        """
        token: str = yield Exclusive(self._fresh_token(rejected))
        return token

    def user_id(self) -> Flow[str]:
        """The logged-in user's id. Authenticates if needed, then is read once and kept."""
        if self._user_id is None:
            yield from self.access_token()
            self._user_id = self.config.tokens.user_id
        return self._user_id

    def send(self, request: Request[T]) -> Flow[T]:
        """Send one request with auth, pacing and retries, and parse the answer."""
        if request.method != "GET":
            raise ValueError(f"beli is read-only; refusing {request.method} {request.path}")
        token = yield from self.access_token()
        base_url = yield from self._base_url(request.host, token)
        reauthed = False
        attempt = 0
        while True:
            token = yield from self.access_token()
            reply = yield Call(
                "GET", base_url + request.path, params=request.params, headers=self._headers(token)
            )
            if isinstance(reply, httpx.TransportError):
                if attempt >= self.config.max_retries:
                    raise reply
                yield Sleep(retry_delay(None, attempt))
                attempt += 1
                continue
            response: httpx.Response = reply
            if response.status_code == 401 and not reauthed:
                reauthed = True
                yield from self.access_token(rejected=token)
                continue
            if response.status_code in RETRY_STATUSES and attempt < self.config.max_retries:
                yield Sleep(retry_delay(response, attempt))
                attempt += 1
                continue
            if response.status_code >= 400:
                raise error_for(response)
            return request.parse(decode(response))

    def run(self, plan: Plan[T]) -> Flow[T]:
        """Send each request a plan yields and hand it the parsed result."""
        result: Any = None
        error: APIError | None = None
        while True:
            try:
                request = plan.throw(error) if error is not None else plan.send(result)
            except StopIteration as stop:
                value: T = stop.value
                return value
            result, error = None, None
            try:
                result = yield from self.send(request)
            except APIError as exc:
                error = exc

    def _headers(self, token: str) -> dict[str, str]:
        return {**self.config.headers(), "Authorization": f"Bearer {token}"}

    def _base_url(self, host: str, token: str) -> Flow[str]:
        if host not in self.hosts:
            return host.rstrip("/")
        # Nothing in the discovery response names the onboarding host.
        if host != "onboard" and not self._hosts_known:
            yield Exclusive(self._discover_hosts(token))
        return self.hosts[host]

    # Run under the auth lock

    def _discover_hosts(self, token: str) -> Flow[None]:
        """Ask the API which hosts to use. Tried once per client; any failure keeps the fallbacks."""
        if self._hosts_known:
            return
        reply = yield Call("GET", self.hosts["api"] + HOSTS_PATH, headers=self._headers(token))
        found: dict[str, str] = {}
        if isinstance(reply, httpx.Response) and reply.status_code == 200:
            found = parse_hosts(decode(reply))
        self.hosts.update(found)
        self._hosts_known = True
        if found:
            log.debug("hosts discovered from %s: %s", HOSTS_PATH, found)
        else:
            log.debug("host discovery gave nothing usable; keeping the built-in hosts")

    def _auth_post(self, path: str, body: dict[str, str]) -> Flow[httpx.Response]:
        url = self.hosts["onboard"] + path
        reply = yield Call("POST", url, json=body, headers=self.config.headers())
        if isinstance(reply, httpx.TransportError):
            raise reply
        response: httpx.Response = reply
        return response

    def _login(self) -> Flow[Tokens]:
        response = yield from self._auth_post("/api/token/", self.config.login_body())
        if response.status_code != 200:
            raise _auth_failure(response, "Login")
        data = response.json()
        self.config.tokens = Tokens(access=data["access"], refresh=data["refresh"])
        self._user_id = self.config.tokens.user_id
        self.config.store()
        return self.config.tokens

    def _fresh_token(self, rejected: str | None) -> Flow[str]:
        # Holding the auth lock: only one caller at a time gets past this point,
        # so the checks below see the result of whoever went first. Several
        # threads that find the token expired, or that were all refused with
        # the same token, produce one refresh between them.
        tokens = self.config.tokens
        if tokens.access != rejected and not is_expired(tokens.access):
            return tokens.access
        if not is_expired(tokens.refresh, skew=0):
            response = yield from self._auth_post(
                "/api/token/refresh/", {"refresh": tokens.refresh}
            )
            if response.status_code == 200:
                data = response.json()
                # Swap the pair in one assignment so a reader never sees half of it.
                self.config.tokens = Tokens(
                    access=data["access"], refresh=data.get("refresh") or tokens.refresh
                )
                self.config.store()
                return self.config.tokens.access
        return (yield from self._login()).access
