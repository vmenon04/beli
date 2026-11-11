"""Async resource groups. Mirrors ``_resources`` method for method.

The two files may differ only in ``async``/``await`` and the ``Async`` class
prefix. ``tests/test_parity.py`` fails if they differ in anything else.
"""

from __future__ import annotations

import builtins
from typing import TYPE_CHECKING, Any

from . import _endpoints as ep
from . import _plans as plans
from .models import (
    Bookmark,
    Business,
    BusinessHours,
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

if TYPE_CHECKING:
    from ._transport import AsyncTransport


class AsyncResource:
    def __init__(self, transport: AsyncTransport) -> None:
        self._t = transport

    async def _uid(self, user: str | None) -> str:
        """``user`` if given, else the logged-in user's id."""
        return user or await self._t.user_id()


class AsyncRankings(AsyncResource):
    """Places you've ranked and the 0 to 10 scores Beli gave them."""

    async def list(
        self, category: str = "RES", *, user: str | None = None
    ) -> builtins.list[Ranking]:
        """Rankings in one category, best first."""
        return await self._t.send(ep.rankings(await self._uid(user), category))

    async def all(
        self, categories: builtins.list[str] | None = None, *, user: str | None = None
    ) -> builtins.list[Ranking]:
        """Rankings across every category on the account (or the ones given)."""
        return await self._t.run(plans.all_rankings(await self._uid(None), categories, user))

    async def visit_dates(self, business_id: int) -> builtins.list[str]:
        """ISO dates you logged visits to a place, newest first."""
        return await self._t.send(ep.visit_dates(await self._uid(None), business_id))

    async def count(self, *, user: str | None = None) -> int:
        return await self._t.send(ep.rank_count(await self._uid(user)))

    async def count_this_year(self, year: int | None = None, *, user: str | None = None) -> int:
        return await self._t.send(ep.ranked_this_year(await self._uid(user), year))


class AsyncScores(AsyncResource):
    async def list(self, *, user: str | None = None) -> builtins.list[Score]:
        """Every score on the account as ``(business_id, value, category)``."""
        return await self._t.send(ep.scores(await self._uid(user)))

    async def averages(self, *, user: str | None = None) -> ScoreAverages:
        """Average score and count by city, country and cuisine."""
        return await self._t.send(ep.score_averages(await self._uid(user)))


class AsyncNotes(AsyncResource):
    """Written reviews attached to rankings."""

    async def list(self, *, user: str | None = None) -> builtins.list[Note]:
        return await self._t.send(ep.notes(await self._uid(user), None))

    async def get(self, business_id: int, *, user: str | None = None) -> str | None:
        """The note on one place, or ``None`` if there isn't one."""
        return await self._t.send(ep.note_text(await self._uid(user), business_id))


class AsyncPhotos(AsyncResource):
    async def list(self, *, user: str | None = None) -> builtins.list[Photo]:
        return await self._t.send(ep.photos(await self._uid(user)))


class AsyncBookmarks(AsyncResource):
    """Your Want to Try list."""

    async def list(
        self, category: str = "RES", *, user: str | None = None
    ) -> builtins.list[Bookmark]:
        return await self._t.send(ep.bookmarks(await self._uid(user), category))


class AsyncGuides(AsyncResource):
    async def list(self, *, user: str | None = None) -> builtins.list[Guide]:
        return await self._t.send(ep.guides(await self._uid(user)))

    async def items(self, *, user: str | None = None) -> builtins.list[GuideItem]:
        """Places across all of a user's guides. ``item.guide`` is the guide id."""
        return await self._t.send(ep.guide_items(await self._uid(user)))

    async def get(self, guide_id: int) -> Any:
        """One guide in full, as raw JSON."""
        return await self._t.send(ep.guide(await self._uid(None), guide_id))


class AsyncUsers(AsyncResource):
    async def get(self, user_id: str) -> User:
        return await self._t.send(ep.member(user_id))

    async def followers(self, *, user: str | None = None) -> builtins.list[User]:
        return await self._t.send(ep.followers(await self._uid(user)))

    async def following(self, *, user: str | None = None) -> builtins.list[User]:
        return await self._t.send(ep.following(await self._uid(user)))

    async def streak(self, *, user: str | None = None) -> int:
        """Current ranking streak in weeks."""
        return await self._t.send(ep.streak(await self._uid(user)))


class AsyncPlaces(AsyncResource):
    async def search(
        self,
        term: str,
        *,
        city: str | None = None,
        coords: tuple[float, float] | None = None,
    ) -> builtins.list[SearchResult]:
        """Search for places. Check ``result.address``: top hits can be in another city."""
        return await self._t.send(ep.search(await self._uid(None), term, city, coords))

    async def hours(self, business_id: int) -> builtins.list[BusinessHours]:
        return await self._t.send(ep.business_hours(business_id))

    async def trending(self, category: str = "RES") -> builtins.list[Business]:
        return await self._t.send(ep.trending(await self._uid(None), category))
