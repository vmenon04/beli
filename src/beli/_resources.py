"""The resource groups on a client: ``beli.rankings``, ``beli.notes`` and so on.

Each method builds a request with a builder from ``_endpoints`` and hands it
to the transport. ``user=None`` means the logged-in user.

``_async.py`` has an async wrapper for every method here, and
``tests/test_parity.py`` fails if one is missing or its signature differs.
"""

from __future__ import annotations

import builtins
from typing import TYPE_CHECKING, Any

from . import _endpoints as ep
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
    from ._transport import Transport


class Resource:
    def __init__(self, transport: Transport) -> None:
        self._t = transport

    def _uid(self, user: str | None) -> str:
        """``user`` if given, else the logged-in user's id."""
        return user or self._t.user_id()


class Rankings(Resource):
    """Places you've ranked and the 0 to 10 scores Beli gave them."""

    def list(
        self,
        category: str = "RES",
        *,
        user: str | None = None,
        sort: ep.RankingSort | None = None,
    ) -> builtins.list[Ranking]:
        """Rankings in one category, in the order the API returns them.

        ``sort="score"`` puts the highest score first instead. Places with the
        same score keep the API's order.
        """
        return self._t.send(ep.rankings(self._uid(user), category, sort))

    def all(
        self,
        categories: builtins.list[str] | None = None,
        *,
        user: str | None = None,
        sort: ep.RankingSort | None = None,
    ) -> builtins.list[Ranking]:
        """Rankings across every category on the account (or the ones given).

        Categories come one after another. ``sort`` applies within each.
        """
        me = self._uid(None)
        if categories is None:
            categories = [c.code for c in self._t.send(ep.categories(me))] or ["RES"]
        rankings: builtins.list[Ranking] = []
        for code in categories:
            rankings += self.list(code, user=user, sort=sort)
        return rankings

    def visit_dates(self, business_id: int) -> builtins.list[str]:
        """ISO dates you logged visits to a place, newest first."""
        return self._t.send(ep.visit_dates(self._uid(None), business_id))

    def count(self, *, user: str | None = None) -> int:
        return self._t.send(ep.rank_count(self._uid(user)))

    def count_this_year(self, year: int | None = None, *, user: str | None = None) -> int:
        return self._t.send(ep.ranked_this_year(self._uid(user), year))


class Scores(Resource):
    def list(self, *, user: str | None = None) -> builtins.list[Score]:
        """Every score on the account as ``(business_id, value, category)``."""
        return self._t.send(ep.scores(self._uid(user)))

    def averages(self, *, user: str | None = None) -> ScoreAverages:
        """Average score and count by city, country and cuisine."""
        return self._t.send(ep.score_averages(self._uid(user)))


class Notes(Resource):
    """Written reviews attached to rankings."""

    def list(self, *, user: str | None = None) -> builtins.list[Note]:
        return self._t.send(ep.notes(self._uid(user), None))

    def get(self, business_id: int, *, user: str | None = None) -> str | None:
        """The note on one place, or ``None`` if there isn't one."""
        return self._t.send(ep.note_text(self._uid(user), business_id))


class Photos(Resource):
    def list(self, *, user: str | None = None) -> builtins.list[Photo]:
        return self._t.send(ep.photos(self._uid(user)))


class Bookmarks(Resource):
    """Your Want to Try list."""

    def list(self, category: str = "RES", *, user: str | None = None) -> builtins.list[Bookmark]:
        return self._t.send(ep.bookmarks(self._uid(user), category))


class Guides(Resource):
    def list(self, *, user: str | None = None) -> builtins.list[Guide]:
        return self._t.send(ep.guides(self._uid(user)))

    def items(self, *, user: str | None = None) -> builtins.list[GuideItem]:
        """Places across all of a user's guides. ``item.guide`` is the guide id."""
        return self._t.send(ep.guide_items(self._uid(user)))

    def get(self, guide_id: int) -> Any:
        """One guide in full, as raw JSON."""
        return self._t.send(ep.guide(self._uid(None), guide_id))


class Users(Resource):
    def get(self, user_id: str) -> User:
        return self._t.send(ep.member(user_id))

    def followers(self, *, user: str | None = None) -> builtins.list[User]:
        return self._t.send(ep.followers(self._uid(user)))

    def following(self, *, user: str | None = None) -> builtins.list[User]:
        return self._t.send(ep.following(self._uid(user)))

    def streak(self, *, user: str | None = None) -> int:
        """Current ranking streak in weeks."""
        return self._t.send(ep.streak(self._uid(user)))


class Places(Resource):
    def search(
        self,
        term: str,
        *,
        city: str | None = None,
        coords: tuple[float, float] | None = None,
    ) -> builtins.list[SearchResult]:
        """Search for places. Check ``result.address``: top hits can be in another city."""
        return self._t.send(ep.search(self._uid(None), term, city, coords))

    def hours(self, business_id: int) -> builtins.list[BusinessHours]:
        return self._t.send(ep.business_hours(business_id))

    def trending(self, category: str = "RES") -> builtins.list[Business]:
        return self._t.send(ep.trending(self._uid(None), category))
