"""One builder per endpoint. All are reads: this package never changes an account.

Each returns a :class:`Request` for the transport to send. Builders are
pure: one that needs a user takes the id as its first argument, and the
client passes the logged-in user's id when the caller didn't name one.

Paths and parameters come from beli-api-spec (Beli app 10.2.0). Endpoints marked
"verified" there answered on a live account; the rest are from app code only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, TypeVar, get_args

from pydantic import BaseModel, TypeAdapter

from ._constants import GUIDE_FLAGS, NOTES_FIELD
from ._transport import Request
from .models import (
    Bookmark,
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

M = TypeVar("M", bound=BaseModel)

RankingSort = Literal["score"]
"""Client-side orderings ``rankings`` can apply. The default is none: the API's order."""


def results(data: Any) -> list[Any]:
    """Unwrap the envelopes Beli uses: DRF pages, ``{results: [...]}`` or a bare list."""
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        inner = data.get("results", data.get("predictions"))
        if isinstance(inner, list):
            return inner
        if isinstance(inner, dict):
            return [inner]
    return [data]


def list_of(model: type[M]) -> Callable[[Any], list[M]]:
    adapter = TypeAdapter(list[model])  # type: ignore[valid-type]
    return lambda data: adapter.validate_python(results(data))


def one(model: type[M]) -> Callable[[Any], M]:
    def parse(data: Any) -> M:
        items = results(data)
        if not items:
            raise ValueError(f"Empty response, expected {model.__name__}")
        return model.model_validate(items[0])

    return parse


def as_int(data: Any) -> int:
    return int(data or 0)


# Account


def me() -> Request[User]:
    return Request("/api/user/logged-in/", host="onboard", parse=one(User))


def member(user_id: str) -> Request[User]:
    return Request("/api/user/member/", params={"id": user_id}, parse=one(User))


def categories(user_id: str) -> Request[list[Category]]:
    def parse(data: Any) -> list[Category]:
        raw = data.get("categories", []) if isinstance(data, dict) else []
        return [Category.model_validate(c) for c in raw]

    return Request("/api/user-setting/", params={"user": user_id}, parse=parse)


def rank_count(user_id: str) -> Request[int]:
    return Request(f"/api/user-field-count/{user_id}/RANK/", parse=as_int)


def ranked_this_year(user_id: str, year: int | None) -> Request[int]:
    params = {"year": year} if year else None
    return Request(f"/api/count-ranked-this-year/{user_id}/", params=params, parse=as_int)


def app_rank(user_id: str) -> Request[Any]:
    return Request(f"/api/app-rank/{user_id}/")


def streak(user_id: str) -> Request[int]:
    def parse(data: Any) -> int:
        return int(data.get("result", 0)) if isinstance(data, dict) else int(data or 0)

    return Request(
        "/api/user/streak/",
        params={"user": user_id, "has_new_streak_share_page": "true"},
        parse=parse,
    )


# Rankings, scores, notes


def by_score(items: list[Ranking]) -> list[Ranking]:
    """Highest score first, unscored last. Stable, so ties keep the order they came in."""
    return sorted(items, key=lambda r: r.score if r.score is not None else -1, reverse=True)


def rankings(
    user_id: str, category: str, sort: RankingSort | None = None
) -> Request[list[Ranking]]:
    """A user's rankings in one category, in the order the API returns them.

    ``tests/test_live.py::test_ranking_order`` confirmed on a real account
    (2026-11-11) that /api/get-ranking/ answers best first: no row has a
    higher score than the row before it.

    TODO(live): how places with the same score are ordered is still unknown,
    because that account had no tied scores. Beli can show several places at
    one score, and the user's order among them is only recoverable if the
    API's order is the rank order. The same test answers this when run on an
    account that has ties.

    Until then nothing here reorders the response unless asked to with
    ``sort="score"``, and that sort is stable so it cannot lose whatever the
    API's order means for ties. ``Export.rated_places`` numbers ranks with
    the same stable sort.
    """
    if sort is not None and sort not in get_args(RankingSort):
        raise ValueError(f"Unknown sort {sort!r}; use one of {get_args(RankingSort)} or None")

    def parse(data: Any) -> list[Ranking]:
        items = list_of(Ranking)(data)
        return by_score(items) if sort == "score" else items

    return Request(
        "/api/get-ranking/",
        params={"user": user_id, "category": category},
        parse=parse,
    )


def scores(user_id: str) -> Request[list[Score]]:
    return Request(f"/api/user-scores/{user_id}/", parse=list_of(Score))


def score_averages(user_id: str) -> Request[ScoreAverages]:
    return Request(
        f"/api/score-average/{user_id}/ALL/",
        parse=ScoreAverages.model_validate,
    )


def visit_dates(user_id: str, business_id: int) -> Request[list[str]]:
    def parse(data: Any) -> list[str]:
        out = []
        for item in results(data):
            if isinstance(item, dict):
                item = item.get("visit_date") or item.get("date") or item.get("value")
            if item:
                out.append(str(item)[:10])
        return out

    return Request(
        f"/api/visit-dates-on-business/{user_id}/{business_id}/",
        params={"reversed": "true"},
        parse=parse,
    )


def notes(user_id: str, business_id: int | None) -> Request[list[Note]]:
    params: dict[str, Any] = {"field__name": NOTES_FIELD, "user": user_id}
    if business_id is not None:
        params["business"] = business_id

    def parse(data: Any) -> list[Note]:
        items = [Note.model_validate(n) for n in results(data)]
        return [n for n in items if n.end_dt is None]

    return Request("/api/datauserbusinesstext-sparse/", params=params, parse=parse)


def note_text(user_id: str, business_id: int) -> Request[str | None]:
    """The current note on one place, or ``None``."""
    request = notes(user_id, business_id)

    def parse(data: Any) -> str | None:
        matching = [n for n in request.parse(data) if n.business == business_id]
        return matching[-1].value if matching else None

    return Request(request.path, params=request.params, parse=parse)


def photos(user_id: str) -> Request[list[Photo]]:
    return Request("/api/user-business-photos/", params={"user": user_id}, parse=list_of(Photo))


# Bookmarks


def bookmarks(user_id: str, category: str) -> Request[list[Bookmark]]:
    def parse(data: Any) -> list[Bookmark]:
        # Keyed by display name, e.g. {"Restaurants": [...]}
        if isinstance(data, dict) and "results" not in data:
            rows = [row for group in data.values() if isinstance(group, list) for row in group]
        else:
            rows = results(data)
        return [Bookmark.model_validate(r) for r in rows]

    return Request(
        "/api/get-bookmark/",
        params={"user": user_id, "category": category},
        parse=parse,
    )


# Guides


def guides(user_id: str) -> Request[list[Guide]]:
    return Request(
        "/api/user-guide/",
        params={"user_id": user_id, **GUIDE_FLAGS},
        parse=list_of(Guide),
    )


def guide_items(user_id: str) -> Request[list[GuideItem]]:
    return Request(
        "/api/user-guide-items/",
        params={"user_id": user_id, **GUIDE_FLAGS},
        parse=list_of(GuideItem),
    )


def guide(user_id: str, guide_id: int) -> Request[Any]:
    return Request(
        "/api/user-guide-list-view/",
        params={
            "list_id": guide_id,
            "viewer": user_id,
            "check_user_access": "false",
            "playlists_v2": "true",
            "vguides": "true",
            **GUIDE_FLAGS,
        },
    )


# Social


def followers(user_id: str) -> Request[list[User]]:
    return Request(
        f"/api/followers/{user_id}/",
        params={"include_followed": "true"},
        parse=list_of(User),
    )


def following(user_id: str) -> Request[list[User]]:
    return Request(
        f"/api/following/{user_id}/",
        params={"include_followed": "true"},
        parse=list_of(User),
    )


# Places


def search(
    user_id: str, term: str, city: str | None, coords: tuple[float, float] | None
) -> Request[list[SearchResult]]:
    params: dict[str, Any] = {"term": term, "user": user_id}
    if city:
        params["city"] = city
    if coords:
        params["coords"] = f"{coords[0]},{coords[1]}"
    return Request("/api/search-app/", params=params, parse=list_of(SearchResult))


def business_hours(business_id: int) -> Request[list[BusinessHours]]:
    return Request(
        "/api/business-hours/",
        params={"business": business_id},
        parse=list_of(BusinessHours),
    )


def trending(user_id: str, category: str) -> Request[list[Any]]:
    from .models import Business

    return Request(
        f"/api/trending/{user_id}/", params={"category": category}, parse=list_of(Business)
    )


def raw_get(
    user_id: str, path: str, params: dict[str, Any] | None, host: str | None
) -> Request[Any]:
    """Any GET. ``{me}`` in the path or as a whole param value becomes ``user_id``."""
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"  # Django APPEND_SLASH: routes need the trailing slash
    path = path.replace("{me}", user_id)
    if params:
        params = {k: user_id if v == "{me}" else v for k, v in params.items()}
    return Request(path, params=params, host=host or "api")
