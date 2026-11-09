"""The ``Beli`` and ``AsyncBeli`` clients."""

from __future__ import annotations

import os
from collections.abc import Callable
from types import TracebackType
from typing import Any, TypeVar

import httpx

from . import _endpoints as ep
from ._async_resources import (
    AsyncBookmarks,
    AsyncGuides,
    AsyncNotes,
    AsyncPhotos,
    AsyncPlaces,
    AsyncRankings,
    AsyncScores,
    AsyncUsers,
)
from ._auth import Tokens, default_session_path
from ._resources import Bookmarks, Guides, Notes, Photos, Places, Rankings, Scores, Users
from ._transport import AsyncTransport, Config, SyncTransport
from .errors import APIError
from .export import Export
from .models import Bookmark, Category, User

T = TypeVar("T")

PathLike = str | os.PathLike[str]


def _config(
    email: str | None,
    password: str | None,
    phone: str | None,
    access_token: str | None,
    refresh_token: str | None,
    session_file: PathLike | None,
    min_interval: float,
    max_retries: int,
    timeout: float,
    user_agent: str | None,
) -> Config:
    return Config.build(
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
    )


class Beli:
    """Client for the Beli app's private API.

    Credentials are taken from the arguments, then ``BELI_EMAIL`` / ``BELI_PHONE``
    / ``BELI_PASSWORD`` / ``BELI_REFRESH_TOKEN``, then ``session_file`` if given.
    Nothing touches the network until the first call.

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
        http_client: httpx.Client | None = None,
    ) -> None:
        config = _config(
            email,
            password,
            phone,
            access_token,
            refresh_token,
            session_file,
            min_interval,
            max_retries,
            timeout,
            user_agent,
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
        return self._transport.user_id()

    def me(self) -> User:
        return self._transport.send(ep.me())

    def categories(self) -> list[Category]:
        """Category codes enabled on the account (``RES``, ``BAR``, ...)."""
        return self._transport.send(ep.categories())

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        host: str | None = None,
    ) -> Any:
        """Call any endpoint from beli-api-spec. ``{me}`` in the path or a param value is your user id.

        beli.request("GET", "/api/user-field-count/{me}/RANK/")
        """
        return self._transport.send(ep.raw(method, path, params, json, host))

    def export(
        self,
        categories: list[str] | None = None,
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> Export:
        """Fetch rankings, notes, photos, bookmarks and guides in one go."""
        step = on_progress or (lambda _msg: None)
        exp = Export(user=self.me())
        if categories is None:
            step("categories")
            categories = [c.code for c in self.categories()] or ["RES"]
        for code in categories:
            step(f"rankings {code}")
            exp.rankings.extend(self.rankings.list(code))
        step("notes")
        exp.notes = self.notes.list()

        def optional(label: str, fn: Callable[[], T], default: T) -> T:
            step(label)
            try:
                return fn()
            except APIError as exc:
                exp.warnings.append(f"{label}: {exc}")
                return default

        exp.photos = optional("photos", self.photos.list, [])
        bookmarks: list[Bookmark] = []
        for code in categories:

            def fetch(c: str = code) -> list[Bookmark]:
                return self.bookmarks.list(c)

            bookmarks += optional(f"bookmarks {code}", fetch, [])
        exp.bookmarks = bookmarks
        exp.guides = optional("guides", self.guides.list, [])
        exp.guide_items = optional("guide items", self.guides.items, [])
        exp.averages = optional("averages", self.scores.averages, None)
        return exp

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


class AsyncBeli:
    """Async version of :class:`Beli`, with the same resources and arguments.

    async with AsyncBeli.from_session() as beli:
        rankings = await beli.rankings.list()
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
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        config = _config(
            email,
            password,
            phone,
            access_token,
            refresh_token,
            session_file,
            min_interval,
            max_retries,
            timeout,
            user_agent,
        )
        self._transport = AsyncTransport(config, http_client)
        self.rankings = AsyncRankings(self._transport)
        self.scores = AsyncScores(self._transport)
        self.notes = AsyncNotes(self._transport)
        self.photos = AsyncPhotos(self._transport)
        self.bookmarks = AsyncBookmarks(self._transport)
        self.guides = AsyncGuides(self._transport)
        self.users = AsyncUsers(self._transport)
        self.places = AsyncPlaces(self._transport)

    @classmethod
    def from_session(cls, path: PathLike | None = None, **kwargs: Any) -> AsyncBeli:
        return cls(session_file=path or default_session_path(), **kwargs)

    async def login(self) -> Tokens:
        return await self._transport.login()

    @property
    def tokens(self) -> Tokens:
        return self._transport.config.tokens

    async def user_id(self) -> str:
        return await self._transport.user_id()

    async def me(self) -> User:
        return await self._transport.send(ep.me())

    async def categories(self) -> list[Category]:
        return await self._transport.send(ep.categories())

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        host: str | None = None,
    ) -> Any:
        return await self._transport.send(ep.raw(method, path, params, json, host))

    async def export(
        self,
        categories: list[str] | None = None,
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> Export:
        step = on_progress or (lambda _msg: None)
        exp = Export(user=await self.me())
        if categories is None:
            step("categories")
            categories = [c.code for c in await self.categories()] or ["RES"]
        for code in categories:
            step(f"rankings {code}")
            exp.rankings.extend(await self.rankings.list(code))
        step("notes")
        exp.notes = await self.notes.list()

        async def optional(label: str, coro: Any, default: Any) -> Any:
            step(label)
            try:
                return await coro
            except APIError as exc:
                exp.warnings.append(f"{label}: {exc}")
                return default

        exp.photos = await optional("photos", self.photos.list(), [])
        for code in categories:
            exp.bookmarks += await optional(f"bookmarks {code}", self.bookmarks.list(code), [])
        exp.guides = await optional("guides", self.guides.list(), [])
        exp.guide_items = await optional("guide items", self.guides.items(), [])
        exp.averages = await optional("averages", self.scores.averages(), None)
        return exp

    async def close(self) -> None:
        await self._transport.close()

    async def __aenter__(self) -> AsyncBeli:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()
