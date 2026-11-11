"""Operations that take more than one request, written once for both clients.

A plan yields each :class:`~beli._session.Request` it wants sent and receives
the parsed result. It does no I/O itself. ``me`` is the logged-in user's id.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import _endpoints as ep
from ._session import Plan, Request
from .errors import APIError
from .export import Export
from .models import Bookmark, Ranking


def all_rankings(me: str, categories: list[str] | None, user: str | None) -> Plan[list[Ranking]]:
    if categories is None:
        categories = [c.code for c in (yield ep.categories(me))] or ["RES"]
    out: list[Ranking] = []
    for code in categories:
        out.extend((yield ep.rankings(user or me, code)))
    return out


def export(
    me: str, categories: list[str] | None, on_progress: Callable[[str], None] | None
) -> Plan[Export]:
    step = on_progress or (lambda _msg: None)
    exp = Export(user=(yield ep.me()))
    if categories is None:
        step("categories")
        categories = [c.code for c in (yield ep.categories(me))] or ["RES"]
    for code in categories:
        step(f"rankings {code}")
        exp.rankings.extend((yield ep.rankings(me, code)))
    step("notes")
    exp.notes = yield ep.notes(me, None)

    def optional(label: str, request: Request[Any], default: Any) -> Plan[Any]:
        step(label)
        try:
            return (yield request)
        except APIError as exc:
            exp.warnings.append(f"{label}: {exc}")
            return default

    exp.photos = yield from optional("photos", ep.photos(me), [])
    bookmarks: list[Bookmark] = []
    for code in categories:
        bookmarks += yield from optional(f"bookmarks {code}", ep.bookmarks(me, code), [])
    exp.bookmarks = bookmarks
    exp.guides = yield from optional("guides", ep.guides(me), [])
    exp.guide_items = yield from optional("guide items", ep.guide_items(me), [])
    exp.averages = yield from optional("averages", ep.score_averages(me), None)
    return exp
