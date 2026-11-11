"""Sync resource groups. ``_async_resources`` mirrors this file method for method.

Each method builds a request in ``_endpoints`` (or a plan in ``_plans``) and
hands it to the transport, so nothing here can differ between the two clients
except ``await``. ``tests/test_parity.py`` fails if the two files drift.
``user=None`` means the logged-in user.
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
    from ._transport import SyncTransport


class SyncResource:
    def __init__(self, transport: SyncTransport) -> None:
        self._t = transport


class Rankings(SyncResource):
    """Places you've ranked and the 0 to 10 scores Beli gave them."""

    def list(self, category: str = "RES", *, user: str | None = None) -> builtins.list[Ranking]:
        """Rankings in one category, best first."""
        return self._t.send(ep.rankings(category, user))

    def all(
        self, categories: builtins.list[str] | None = None, *, user: str | None = None
    ) -> builtins.list[Ranking]:
        """Rankings across every category on the account (or the ones given)."""
        return self._t.run(plans.all_rankings(categories, user))

    def visit_dates(self, business_id: int) -> builtins.list[str]:
        """ISO dates you logged visits to a place, newest first."""
        return self._t.send(ep.visit_dates(business_id))

    def count(self, *, user: str | None = None) -> int:
        return self._t.send(ep.rank_count(user))

    def count_this_year(self, year: int | None = None, *, user: str | None = None) -> int:
        return self._t.send(ep.ranked_this_year(user, year))


class Scores(SyncResource):
    def list(self, *, user: str | None = None) -> builtins.list[Score]:
        """Every score on the account as ``(business_id, value, category)``."""
        return self._t.send(ep.scores(user))

    def averages(self, *, user: str | None = None) -> ScoreAverages:
        """Average score and count by city, country and cuisine."""
        return self._t.send(ep.score_averages(user))


class Notes(SyncResource):
    """Written reviews attached to rankings."""

    def list(self, *, user: str | None = None) -> builtins.list[Note]:
        return self._t.send(ep.notes(user, None))

    def get(self, business_id: int, *, user: str | None = None) -> str | None:
        """The note on one place, or ``None`` if there isn't one."""
        return self._t.send(ep.note_text(user, business_id))


class Photos(SyncResource):
    def list(self, *, user: str | None = None) -> builtins.list[Photo]:
        return self._t.send(ep.photos(user))


class Bookmarks(SyncResource):
    """Your Want to Try list."""

    def list(self, category: str = "RES", *, user: str | None = None) -> builtins.list[Bookmark]:
        return self._t.send(ep.bookmarks(category, user))


class Guides(SyncResource):
    def list(self, *, user: str | None = None) -> builtins.list[Guide]:
        return self._t.send(ep.guides(user))

    def items(self, *, user: str | None = None) -> builtins.list[GuideItem]:
        """Places across all of a user's guides. ``item.guide`` is the guide id."""
        return self._t.send(ep.guide_items(user))

    def get(self, guide_id: int) -> Any:
        """One guide in full, as raw JSON."""
        return self._t.send(ep.guide(guide_id))


class Users(SyncResource):
    def get(self, user_id: str) -> User:
        return self._t.send(ep.member(user_id))

    def followers(self, *, user: str | None = None) -> builtins.list[User]:
        return self._t.send(ep.followers(user))

    def following(self, *, user: str | None = None) -> builtins.list[User]:
        return self._t.send(ep.following(user))

    def streak(self, *, user: str | None = None) -> int:
        """Current ranking streak in weeks."""
        return self._t.send(ep.streak(user))


class Places(SyncResource):
    def search(
        self,
        term: str,
        *,
        city: str | None = None,
        coords: tuple[float, float] | None = None,
    ) -> builtins.list[SearchResult]:
        """Search for places. Check ``result.address``: top hits can be in another city."""
        return self._t.send(ep.search(term, city, coords))

    def hours(self, business_id: int) -> builtins.list[BusinessHours]:
        return self._t.send(ep.business_hours(business_id))

    def trending(self, category: str = "RES") -> builtins.list[Business]:
        return self._t.send(ep.trending(category))
