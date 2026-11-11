"""The async client. Mirrors ``_client`` method for method.

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
from ._transport import AsyncTransport, Config
from .export import Export
from .models import Category, User

PathLike = str | os.PathLike[str]


class AsyncBeli:
    """Client for the Beli app's private API.

    Credentials are taken from the arguments, then ``BELI_EMAIL`` / ``BELI_PHONE``
    / ``BELI_PASSWORD`` / ``BELI_REFRESH_TOKEN``, then ``session_file`` if given.
    Nothing touches the network until the first call.

        async with AsyncBeli(email="you@example.com", password="...") as beli:
            for r in await beli.rankings.list():
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
        http_client: httpx.AsyncClient | None = None,
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
        """Resume the session saved by ``beli login`` (or by an earlier ``session_file``)."""
        return cls(session_file=path or default_session_path(), **kwargs)

    async def login(self) -> Tokens:
        """Log in now instead of on the first call. Returns the new tokens."""
        return await self._transport.login()

    @property
    def tokens(self) -> Tokens:
        """Current tokens. Save ``tokens.refresh`` to resume for about a week without a password."""
        return self._transport.config.tokens

    async def user_id(self) -> str:
        """Your user id. A property here; ``await beli.user_id()`` on the async client."""
        return await self._transport.user_id()

    async def me(self) -> User:
        return await self._transport.send(ep.me())

    async def categories(self) -> list[Category]:
        """Category codes enabled on the account (``RES``, ``BAR``, ...)."""
        return await self._transport.send(ep.categories(await self._transport.user_id()))

    async def get(
        self, path: str, *, params: dict[str, Any] | None = None, host: str | None = None
    ) -> Any:
        """GET any endpoint from beli-api-spec. ``{me}`` in the path or a param value is your user id.

        beli.get("/api/user-field-count/{me}/RANK/")
        """
        return await self._transport.send(
            ep.raw_get(await self._transport.user_id(), path, params, host)
        )

    async def export(
        self,
        categories: list[str] | None = None,
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> Export:
        """Fetch rankings, notes, photos, bookmarks and guides in one go."""
        return await self._transport.run(
            plans.export(await self._transport.user_id(), categories, on_progress)
        )

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
