"""``AsyncBeli``: the same client for ``asyncio`` code.

There is one implementation of the client, the blocking one in ``_client.py``.
``AsyncBeli`` owns a ``Beli`` and one background thread, and every method here
runs the ``Beli`` method of the same name on that thread and awaits the
result. The event loop is never blocked.

Requests are spaced a second apart anyway, so one thread loses nothing. Two
things follow from the design: calls made at the same time queue up and run
one after another, and cancelling a call stops the wait but lets the request
that is already on the wire finish.

Every public method of ``Beli`` and its resources needs a wrapper here with
the same signature. ``tests/test_parity.py`` fails if one is missing.
"""

from __future__ import annotations

import asyncio
import builtins
import functools
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from types import TracebackType
from typing import Any, ParamSpec, TypeVar

import httpx

from . import _endpoints as ep
from . import _resources as sync
from ._auth import Tokens, default_session_path
from ._client import Beli
from .export import Export
from .models import (
    Bookmark,
    Business,
    BusinessHours,
    Category,
    Guide,
    GuideItem,
    Note,
    Photo,
    Ranking,
    Score,
    ScoreAverages,
    SearchResult,
    User,
)

P = ParamSpec("P")
T = TypeVar("T")

PathLike = str | os.PathLike[str]


class _Worker:
    """Runs blocking calls on one background thread."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="beli")

    async def run(self, fn: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, functools.partial(fn, *args, **kwargs))

    def stop(self) -> None:
        self._executor.shutdown(wait=False)


class AsyncRankings:
    """Places you've ranked and the 0 to 10 scores Beli gave them."""

    def __init__(self, rankings: sync.Rankings, worker: _Worker) -> None:
        self._sync, self._run = rankings, worker.run

    async def list(
        self,
        category: str = "RES",
        *,
        user: str | None = None,
        sort: ep.RankingSort | None = None,
    ) -> builtins.list[Ranking]:
        return await self._run(self._sync.list, category, user=user, sort=sort)

    async def all(
        self,
        categories: builtins.list[str] | None = None,
        *,
        user: str | None = None,
        sort: ep.RankingSort | None = None,
    ) -> builtins.list[Ranking]:
        return await self._run(self._sync.all, categories, user=user, sort=sort)

    async def visit_dates(self, business_id: int) -> builtins.list[str]:
        return await self._run(self._sync.visit_dates, business_id)

    async def count(self, *, user: str | None = None) -> int:
        return await self._run(self._sync.count, user=user)

    async def count_this_year(self, year: int | None = None, *, user: str | None = None) -> int:
        return await self._run(self._sync.count_this_year, year, user=user)


class AsyncScores:
    def __init__(self, scores: sync.Scores, worker: _Worker) -> None:
        self._sync, self._run = scores, worker.run

    async def list(self, *, user: str | None = None) -> builtins.list[Score]:
        return await self._run(self._sync.list, user=user)

    async def averages(self, *, user: str | None = None) -> ScoreAverages:
        return await self._run(self._sync.averages, user=user)


class AsyncNotes:
    """Written reviews attached to rankings."""

    def __init__(self, notes: sync.Notes, worker: _Worker) -> None:
        self._sync, self._run = notes, worker.run

    async def list(self, *, user: str | None = None) -> builtins.list[Note]:
        return await self._run(self._sync.list, user=user)

    async def get(self, business_id: int, *, user: str | None = None) -> str | None:
        return await self._run(self._sync.get, business_id, user=user)


class AsyncPhotos:
    def __init__(self, photos: sync.Photos, worker: _Worker) -> None:
        self._sync, self._run = photos, worker.run

    async def list(self, *, user: str | None = None) -> builtins.list[Photo]:
        return await self._run(self._sync.list, user=user)


class AsyncBookmarks:
    """Your Want to Try list."""

    def __init__(self, bookmarks: sync.Bookmarks, worker: _Worker) -> None:
        self._sync, self._run = bookmarks, worker.run

    async def list(
        self, category: str = "RES", *, user: str | None = None
    ) -> builtins.list[Bookmark]:
        return await self._run(self._sync.list, category, user=user)


class AsyncGuides:
    def __init__(self, guides: sync.Guides, worker: _Worker) -> None:
        self._sync, self._run = guides, worker.run

    async def list(self, *, user: str | None = None) -> builtins.list[Guide]:
        return await self._run(self._sync.list, user=user)

    async def items(self, *, user: str | None = None) -> builtins.list[GuideItem]:
        return await self._run(self._sync.items, user=user)

    async def get(self, guide_id: int) -> Any:
        return await self._run(self._sync.get, guide_id)


class AsyncUsers:
    def __init__(self, users: sync.Users, worker: _Worker) -> None:
        self._sync, self._run = users, worker.run

    async def get(self, user_id: str) -> User:
        return await self._run(self._sync.get, user_id)

    async def followers(self, *, user: str | None = None) -> builtins.list[User]:
        return await self._run(self._sync.followers, user=user)

    async def following(self, *, user: str | None = None) -> builtins.list[User]:
        return await self._run(self._sync.following, user=user)

    async def streak(self, *, user: str | None = None) -> int:
        return await self._run(self._sync.streak, user=user)


class AsyncPlaces:
    def __init__(self, places: sync.Places, worker: _Worker) -> None:
        self._sync, self._run = places, worker.run

    async def search(
        self,
        term: str,
        *,
        city: str | None = None,
        coords: tuple[float, float] | None = None,
    ) -> builtins.list[SearchResult]:
        return await self._run(self._sync.search, term, city=city, coords=coords)

    async def hours(self, business_id: int) -> builtins.list[BusinessHours]:
        return await self._run(self._sync.hours, business_id)

    async def trending(self, category: str = "RES") -> builtins.list[Business]:
        return await self._run(self._sync.trending, category)


class AsyncBeli:
    """``Beli`` for ``asyncio`` code. Same arguments, same methods, each one awaited.

        async with AsyncBeli(email="you@example.com", password="...") as beli:
            for r in await beli.rankings.list():
                print(r.score, r.business.name)

    See :class:`Beli` for what the arguments mean. The one difference in
    shape is ``user_id``: a property on ``Beli``, ``await beli.user_id()`` here.
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
        self._sync = Beli(
            email,
            password,
            phone=phone,
            access_token=access_token,
            refresh_token=refresh_token,
            session_file=session_file,
            min_interval=min_interval,
            max_retries=max_retries,
            timeout=timeout,
            user_agent=user_agent,
            discover_hosts=discover_hosts,
            http_client=http_client,
        )
        self._worker = _Worker()
        self._run = self._worker.run
        self.rankings = AsyncRankings(self._sync.rankings, self._worker)
        self.scores = AsyncScores(self._sync.scores, self._worker)
        self.notes = AsyncNotes(self._sync.notes, self._worker)
        self.photos = AsyncPhotos(self._sync.photos, self._worker)
        self.bookmarks = AsyncBookmarks(self._sync.bookmarks, self._worker)
        self.guides = AsyncGuides(self._sync.guides, self._worker)
        self.users = AsyncUsers(self._sync.users, self._worker)
        self.places = AsyncPlaces(self._sync.places, self._worker)

    @classmethod
    def from_session(cls, path: PathLike | None = None, **kwargs: Any) -> AsyncBeli:
        """Resume the session saved by ``beli login`` (or by an earlier ``session_file``)."""
        return cls(session_file=path or default_session_path(), **kwargs)

    async def login(self) -> Tokens:
        return await self._run(self._sync.login)

    @property
    def tokens(self) -> Tokens:
        return self._sync.tokens

    async def user_id(self) -> str:
        return await self._run(lambda: self._sync.user_id)

    async def me(self) -> User:
        return await self._run(self._sync.me)

    async def categories(self) -> list[Category]:
        return await self._run(self._sync.categories)

    async def get(
        self, path: str, *, params: dict[str, Any] | None = None, host: str | None = None
    ) -> Any:
        return await self._run(self._sync.get, path, params=params, host=host)

    async def export(
        self,
        categories: list[str] | None = None,
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> Export:
        """As ``Beli.export``. ``on_progress`` is called from the background thread."""
        return await self._run(self._sync.export, categories, on_progress=on_progress)

    async def close(self) -> None:
        await self._run(self._sync.close)
        self._worker.stop()

    async def __aenter__(self) -> AsyncBeli:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()
