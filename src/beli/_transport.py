"""Sends requests to Beli: login, token refresh, pacing, retries and host discovery.

Every request this package makes leaves through :meth:`Transport._exchange`,
which is also the read-only guard. A :class:`Transport` is safe to share
between threads.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Generic, TypeVar

import httpx

from ._auth import Credentials, Tokens, is_expired, save_tokens
from ._constants import DEFAULT_USER_AGENT, DISCOVERED_HOSTS, FALLBACK_HOSTS, HOSTS_PATH, ORIGIN
from .errors import (
    AuthenticationError,
    UnexpectedResponseError,
    describe_parse_failure,
    error_for,
)

T = TypeVar("T")

log = logging.getLogger("beli")

LOGIN_PATH = "/api/token/"
REFRESH_PATH = "/api/token/refresh/"
AUTH_PATHS = frozenset({LOGIN_PATH, REFRESH_PATH})
"""The only paths that may be sent anything other than a GET."""

RETRY_STATUSES = frozenset({429, 502, 503, 504})

PARSE_FAILURES = (ValueError, LookupError, TypeError, AttributeError)
"""What a parser raises when a response is not what it was written for."""


def _identity(data: Any) -> Any:
    return data


@dataclass(frozen=True)
class Request(Generic[T]):
    """One GET: where to send it and how to parse the answer.

    ``host`` is a service name (``"api"``, ``"onboard"`` or ``"recs"``), which
    the transport maps to a base URL, or a full base URL to use as given.
    """

    path: str
    params: Mapping[str, Any] | None = None
    host: str = "api"
    parse: Callable[[Any], T] = _identity


class Transport:
    def __init__(
        self,
        credentials: Credentials,
        *,
        session_file: Path | None = None,
        min_interval: float = 1.0,
        max_retries: int = 4,
        timeout: float = 30.0,
        user_agent: str | None = None,
        discover_hosts: bool = True,
        http: httpx.Client | None = None,
    ) -> None:
        self.credentials = credentials
        self.tokens = credentials.tokens
        self.session_file = session_file
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.hosts = dict(FALLBACK_HOSTS)
        self._hosts_known = not discover_hosts
        self._user_id: str | None = None
        self._owns_http = http is None
        self._http = http or httpx.Client(timeout=timeout)
        # One lock so that only one thread logs in, refreshes or discovers hosts
        # at a time, and one so that requests are spaced out across threads.
        self._auth_lock = threading.Lock()
        self._pace_lock = threading.Lock()
        self._last_request = 0.0

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    # Sending

    def send(self, request: Request[T]) -> T:
        """Send one request with auth, pacing and retries, and parse the answer."""
        base_url = self._base_url(request.host)
        retries = 0
        reauthenticated = False
        while True:
            token = self.access_token()
            try:
                response = self._exchange(
                    "GET", base_url + request.path, params=request.params, token=token
                )
            except httpx.TransportError:
                if retries >= self.max_retries:
                    raise
                time.sleep(retry_delay(None, retries))
                retries += 1
                continue
            if response.status_code == 401 and not reauthenticated:
                reauthenticated = True
                self.access_token(rejected=token)
                continue
            if response.status_code in RETRY_STATUSES and retries < self.max_retries:
                time.sleep(retry_delay(response, retries))
                retries += 1
                continue
            if response.status_code >= 400:
                raise error_for(response)
            try:
                return request.parse(decode(response))
            except PARSE_FAILURES as exc:
                problem = describe_parse_failure(exc)
                raise UnexpectedResponseError("GET", request.path, problem) from exc

    def _exchange(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        token: str | None = None,
    ) -> httpx.Response:
        """Perform one HTTP exchange. This is the read-only guard.

        Anything that is not a GET without a body, or a POST to login or token
        refresh, is refused before it is sent.
        """
        path = httpx.URL(url).path
        is_read = method == "GET" and json is None
        is_auth = method == "POST" and path in AUTH_PATHS
        if not (is_read or is_auth):
            raise ValueError(f"beli is read-only; refusing {method} {path}")

        headers = {"Origin": ORIGIN, "User-Agent": self.user_agent, "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with self._pace_lock:
            wait = self.min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
        return self._http.request(method, url, params=params, json=json, headers=headers)

    # Authentication

    def login(self) -> Tokens:
        """Log in with the password now, replacing any tokens held."""
        with self._auth_lock:
            return self._login()

    def access_token(self, *, rejected: str | None = None) -> str:
        """A usable access token, refreshing or logging in if needed.

        ``rejected`` is a token the API just answered 401 to. It is replaced
        even if it has not expired, unless another thread already replaced it.
        """
        # Only one thread at a time gets past this line, so the checks below
        # see the result of whoever went first: several threads that find the
        # token expired produce one refresh between them.
        with self._auth_lock:
            tokens = self.tokens
            if tokens.access != rejected and not is_expired(tokens.access):
                return tokens.access
            if not is_expired(tokens.refresh, skew=0):
                url = self.hosts["onboard"] + REFRESH_PATH
                response = self._exchange("POST", url, json={"refresh": tokens.refresh})
                if response.status_code == 200:
                    data = response.json()
                    refresh = data.get("refresh") or tokens.refresh
                    return self._keep(Tokens(access=data["access"], refresh=refresh)).access
            return self._login().access

    def user_id(self) -> str:
        """The logged-in user's id, read from the token. Authenticates if needed."""
        if self._user_id is None:
            self.access_token()
            self._user_id = self.tokens.user_id
        return self._user_id

    def _login(self) -> Tokens:
        """Caller holds the auth lock."""
        body = self.credentials.login_body()
        response = self._exchange("POST", self.hosts["onboard"] + LOGIN_PATH, json=body)
        if response.status_code != 200:
            detail = decode(response)
            if isinstance(detail, dict):
                detail = detail.get("detail", detail)
            raise AuthenticationError(f"Login failed (HTTP {response.status_code}): {detail}")
        data = response.json()
        tokens = self._keep(Tokens(access=data["access"], refresh=data["refresh"]))
        self._user_id = tokens.user_id
        return tokens

    def _keep(self, tokens: Tokens) -> Tokens:
        # One assignment, so another thread never sees half of a new pair.
        self.tokens = tokens
        if self.session_file is not None:
            save_tokens(self.session_file, tokens)
        return tokens

    # Hosts

    def _base_url(self, host: str) -> str:
        if host not in self.hosts:
            return host.rstrip("/")
        # Nothing in the discovery response names the onboarding host.
        if host != "onboard" and not self._hosts_known:
            token = self.access_token()
            with self._auth_lock:
                if not self._hosts_known:
                    self._discover_hosts(token)
        return self.hosts[host]

    def _discover_hosts(self, token: str) -> None:
        """Ask the API which hosts to use. Tried once; any failure keeps the built-in ones."""
        found: dict[str, str] = {}
        try:
            response = self._exchange("GET", self.hosts["api"] + HOSTS_PATH, token=token)
            if response.status_code == 200:
                found = parse_hosts(decode(response))
        except httpx.TransportError:
            pass
        self.hosts.update(found)
        self._hosts_known = True
        if found:
            log.debug("hosts discovered from %s: %s", HOSTS_PATH, found)
        else:
            log.debug("host discovery gave nothing usable; keeping the built-in hosts")


def retry_delay(response: httpx.Response | None, attempt: int) -> float:
    """Seconds to wait before a retry: the ``Retry-After`` header, else exponential backoff."""
    if response is not None and (header := response.headers.get("Retry-After")):
        try:
            return min(float(header), 120.0)
        except ValueError:
            try:
                return max(0.0, parsedate_to_datetime(header).timestamp() - time.time())
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


_HOST = re.compile(r"(?:https://)?([A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::\d+)?)/?")


def parse_hosts(data: Any) -> dict[str, str]:
    """Pick the base URLs this package uses out of an api-hosts response.

    Tokens are sent to whatever this returns, so a value is used only if it is
    a bare host name or an ``https://`` origin with no path. Anything else is
    skipped and the built-in host stays in place.
    """
    found: dict[str, str] = {}
    if not isinstance(data, dict):
        return found
    for key, service in DISCOVERED_HOSTS.items():
        value = data.get(key)
        if isinstance(value, str) and (match := _HOST.fullmatch(value.strip())):
            found[service] = "https://" + match.group(1)
    return found
