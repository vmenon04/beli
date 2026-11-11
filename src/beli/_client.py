"""The sync client. ``_async_client`` mirrors this file method for method.

``tests/test_parity.py`` fails if the two differ in anything but ``await``.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from types import TracebackType
from typing import Any

import httpx

from . import _endpoints as ep
from . import _plans as plans
from ._auth import Tokens, default_session_path
from ._resources import Bookmarks, Guides, Notes, Photos, Places, Rankings, Scores, Users
from ._transport import Config, SyncTransport
from .export import Export
from .models import Category, User

PathLike = str | os.PathLike[str]


class Beli:
    """Client for the Beli app's private API.

    Credentials are taken from the arguments, then ``BELI_EMAIL`` / ``BELI_PHONE``
    / ``BELI_PASSWORD`` / ``BELI_REFRESH_TOKEN``, then ``session_file`` if given.
    Nothing touches the network until the first call.

    Before the first request to the main API the client asks Beli which hosts
    to use (``/api/api-hosts/``) and remembers the answer for its lifetime. If
    that fails it uses the built-in hosts. ``discover_hosts=False`` skips the
    question.

        with Beli(email="you@example.com", password="...") as beli:
            for r in beli.rankings.list():
                print(r.score, r.business.name)
    """

    def __init__(
        self,
        email: str | None = None,
        password: str | None = None,
        *,
        phone: str | None = None,
        access_token: str | None = None,
        refresh_token: str | None = None,
        session_file: PathLike | None = None,
        min_interval: float = 1.0,
        max_retries: int = 4,
        timeout: float = 30.0,
        user_agent: str | None = None,
        discover_hosts: bool = True,
        http_client: httpx.Client | None = None,
    ) -> None:
        config = Config.build(
            email=email,
            phone=phone,
            password=password,
            access_token=access_token,
            refresh_token=refresh_token,
            session_file=session_file,
            min_interval=min_interval,
            max_retries=max_retries,
            timeout=timeout,
            user_agent=user_agent,
            discover_hosts=discover_hosts,
        )
        self._transport = SyncTransport(config, http_client)
        self.rankings = Rankings(self._transport)
        self.scores = Scores(self._transport)
        self.notes = Notes(self._transport)
        self.photos = Photos(self._transport)
        self.bookmarks = Bookmarks(self._transport)
        self.guides = Guides(self._transport)
        self.users = Users(self._transport)
        self.places = Places(self._transport)

    @classmethod
    def from_session(cls, path: PathLike | None = None, **kwargs: Any) -> Beli:
        """Resume the session saved by ``beli login`` (or by an earlier ``session_file``)."""
        return cls(session_file=path or default_session_path(), **kwargs)

    def login(self) -> Tokens:
        """Log in now instead of on the first call. Returns the new tokens."""
        return self._transport.login()

    @property
    def tokens(self) -> Tokens:
        """Current tokens. Save ``tokens.refresh`` to resume for about a week without a password."""
        return self._transport.config.tokens

    @property
    def user_id(self) -> str:
        """Your user id. A property here; ``await beli.user_id()`` on the async client."""
        return self._transport.user_id()

    def me(self) -> User:
        return self._transport.send(ep.me())

    def categories(self) -> list[Category]:
        """Category codes enabled on the account (``RES``, ``BAR``, ...)."""
        return self._transport.send(ep.categories(self._transport.user_id()))

    def get(
        self, path: str, *, params: dict[str, Any] | None = None, host: str | None = None
    ) -> Any:
        """GET any endpoint from beli-api-spec. ``{me}`` in the path or a param value is your user id.

        ``host`` is ``"api"`` (the default), ``"onboard"``, ``"recs"`` or a full base URL.

        beli.get("/api/user-field-count/{me}/RANK/")
        """
        return self._transport.send(ep.raw_get(self._transport.user_id(), path, params, host))

    def export(
        self,
        categories: list[str] | None = None,
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> Export:
        """Fetch rankings, notes, photos, bookmarks and guides in one go."""
        return self._transport.run(plans.export(self._transport.user_id(), categories, on_progress))

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> Beli:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
