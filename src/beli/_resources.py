"""Sync resource groups. ``scripts/gen_async.py`` generates the async twins.

Each method builds a request in ``_endpoints`` and sends it. ``user=None``
means the logged-in user.
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
    from ._transport import SyncTransport


class SyncResource:
    def __init__(self, transport: SyncTransport) -> None:
        self._send = transport.send


class Rankings(SyncResource):
    """Places you've ranked and the 0 to 10 scores Beli gave them."""

    def list(self, category: str = "RES", *, user: str | None = None) -> builtins.list[Ranking]:
        """Rankings in one category, best first."""
        items = self._send(ep.rankings(category, user))
        return sorted(items, key=lambda r: r.score if r.score is not None else -1, reverse=True)

    def all(
        self, categories: builtins.list[str] | None = None, *, user: str | None = None
    ) -> builtins.list[Ranking]:
        """Rankings across every category on the account (or the ones given)."""
        if categories is None:
            categories = [c.code for c in self._send(ep.categories())] or ["RES"]
        out: builtins.list[Ranking] = []
        for code in categories:
            out.extend(self.list(code, user=user))
        return out

    def visit_dates(self, business_id: int) -> builtins.list[str]:
        """ISO dates you logged visits to a place, newest first."""
        return self._send(ep.visit_dates(business_id))

    def count(self, *, user: str | None = None) -> int:
        return self._send(ep.rank_count(user))

    def count_this_year(self, year: int | None = None, *, user: str | None = None) -> int:
        return self._send(ep.ranked_this_year(user, year))

    def delete(self, ranking_id: int) -> Any:
        """Remove a ranking (Beli soft-deletes it). This writes to your account."""
        return self._send(ep.delete_ranking(ranking_id))


class Scores(SyncResource):
    def list(self, *, user: str | None = None) -> builtins.list[Score]:
        """Every score on the account as ``(business_id, value, category)``."""
        return self._send(ep.scores(user))

    def averages(self, *, user: str | None = None) -> ScoreAverages:
        """Average score and count by city, country and cuisine."""
        return self._send(ep.score_averages(user))


class Notes(SyncResource):
    """Written reviews attached to rankings."""

    def list(self, *, user: str | None = None) -> builtins.list[Note]:
        return self._send(ep.notes(user, None))

    def get(self, business_id: int, *, user: str | None = None) -> str | None:
        notes = self._send(ep.notes(user, business_id))
        matching = [n for n in notes if n.business == business_id]
        return matching[-1].value if matching else None

    def set(self, business_id: int, text: str) -> Any:
        """Write or replace your note on a place. This writes to your account."""
        return self._send(ep.set_note(business_id, text))


class Photos(SyncResource):
    def list(self, *, user: str | None = None) -> builtins.list[Photo]:
        return self._send(ep.photos(user))


class Bookmarks(SyncResource):
    """Your Want to Try list."""

    def list(self, category: str = "RES", *, user: str | None = None) -> builtins.list[Bookmark]:
        return self._send(ep.bookmarks(category, user))

    def status(self, business_id: int) -> Any:
        return self._send(ep.bookmark_status(business_id))

    def add(self, business_id: int, category: str = "RES") -> Any:
        """Bookmark a place. Idempotent. This writes to your account."""
        return self._send(ep.add_bookmark(business_id, category))

    def remove(self, business_id: int, category: str = "RES") -> Any:
        """Remove a bookmark. This writes to your account."""
        return self._send(ep.remove_bookmark(business_id, category))


class Guides(SyncResource):
    def list(self, *, user: str | None = None) -> builtins.list[Guide]:
        return self._send(ep.guides(user))

    def items(self, *, user: str | None = None) -> builtins.list[GuideItem]:
        """Places across all of a user's guides. ``item.guide`` is the guide id."""
        return self._send(ep.guide_items(user))

    def get(self, guide_id: int) -> Any:
        """One guide in full, as raw JSON."""
        return self._send(ep.guide(guide_id))


class Users(SyncResource):
    def get(self, user_id: str) -> User:
        return self._send(ep.member(user_id))

    def followers(self, *, user: str | None = None) -> builtins.list[User]:
        return self._send(ep.followers(user))

    def following(self, *, user: str | None = None) -> builtins.list[User]:
        return self._send(ep.following(user))

    def streak(self, *, user: str | None = None) -> int:
        """Current ranking streak in weeks."""
        return self._send(ep.streak(user))


class Places(SyncResource):
    def search(
        self,
        term: str,
        *,
        city: str | None = None,
        coords: tuple[float, float] | None = None,
    ) -> builtins.list[SearchResult]:
        """Search for places. Check ``result.address``: top hits can be in another city."""
        return self._send(ep.search(term, city, coords))

    def hours(self, business_id: int) -> builtins.list[BusinessHours]:
        return self._send(ep.business_hours(business_id))

    def trending(self, category: str = "RES") -> builtins.list[Business]:
        return self._send(ep.trending(category))
