"""One builder per endpoint. All are reads: this package never changes an account.

 Each returns a :class:`Request` that either client can send.

Paths and parameters come from beli-api-spec (Beli app 10.2.0). Endpoints marked
"verified" there answered on a live account; the rest are from app code only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, TypeAdapter

from ._constants import GUIDE_FLAGS, HOST_ONBOARD, NOTES_FIELD
from ._session import ME, Request
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


def user_param(user: str | None) -> str:
    return user or ME


# Account


def me() -> Request[User]:
    return Request("GET", "/api/user/logged-in/", host=HOST_ONBOARD, parse=one(User))


def member(user_id: str) -> Request[User]:
    return Request("GET", "/api/user/member/", params={"id": user_id}, parse=one(User))


def categories() -> Request[list[Category]]:
    def parse(data: Any) -> list[Category]:
        raw = data.get("categories", []) if isinstance(data, dict) else []
        return [Category.model_validate(c) for c in raw]

    return Request("GET", "/api/user-setting/", params={"user": ME}, parse=parse)


def rank_count(user: str | None) -> Request[int]:
    return Request("GET", f"/api/user-field-count/{user_param(user)}/RANK/", parse=as_int)


def ranked_this_year(user: str | None, year: int | None) -> Request[int]:
    params = {"year": year} if year else None
    return Request(
        "GET", f"/api/count-ranked-this-year/{user_param(user)}/", params=params, parse=as_int
    )


def app_rank(user: str | None) -> Request[Any]:
    return Request("GET", f"/api/app-rank/{user_param(user)}/")


def streak(user: str | None) -> Request[int]:
    def parse(data: Any) -> int:
        return int(data.get("result", 0)) if isinstance(data, dict) else int(data or 0)

    return Request(
        "GET",
        "/api/user/streak/",
        params={"user": user_param(user), "has_new_streak_share_page": "true"},
        parse=parse,
    )


# Rankings, scores, notes


def rankings(category: str, user: str | None) -> Request[list[Ranking]]:
    def parse(data: Any) -> list[Ranking]:
        items = list_of(Ranking)(data)
        return sorted(items, key=lambda r: r.score if r.score is not None else -1, reverse=True)

    return Request(
        "GET",
        "/api/get-ranking/",
        params={"user": user_param(user), "category": category},
        parse=parse,
    )


def scores(user: str | None) -> Request[list[Score]]:
    return Request("GET", f"/api/user-scores/{user_param(user)}/", parse=list_of(Score))


def score_averages(user: str | None) -> Request[ScoreAverages]:
    return Request(
        "GET",
        f"/api/score-average/{user_param(user)}/ALL/",
        parse=ScoreAverages.model_validate,
    )


def visit_dates(business_id: int) -> Request[list[str]]:
    def parse(data: Any) -> list[str]:
        out = []
        for item in results(data):
            if isinstance(item, dict):
                item = item.get("visit_date") or item.get("date") or item.get("value")
            if item:
                out.append(str(item)[:10])
        return out

    return Request(
        "GET",
        f"/api/visit-dates-on-business/{ME}/{business_id}/",
        params={"reversed": "true"},
        parse=parse,
    )


def notes(user: str | None, business_id: int | None) -> Request[list[Note]]:
    params: dict[str, Any] = {"field__name": NOTES_FIELD, "user": user_param(user)}
    if business_id is not None:
        params["business"] = business_id

    def parse(data: Any) -> list[Note]:
        items = [Note.model_validate(n) for n in results(data)]
        return [n for n in items if n.end_dt is None]

    return Request("GET", "/api/datauserbusinesstext-sparse/", params=params, parse=parse)


def note_text(user: str | None, business_id: int) -> Request[str | None]:
    """The current note on one place, or ``None``."""
    request = notes(user, business_id)

    def parse(data: Any) -> str | None:
        matching = [n for n in request.parse(data) if n.business == business_id]
        return matching[-1].value if matching else None

    return Request("GET", request.path, params=request.params, parse=parse)


def photos(user: str | None) -> Request[list[Photo]]:
    return Request(
        "GET", "/api/user-business-photos/", params={"user": user_param(user)}, parse=list_of(Photo)
    )


# Bookmarks


def bookmarks(category: str, user: str | None) -> Request[list[Bookmark]]:
    def parse(data: Any) -> list[Bookmark]:
        # Keyed by display name, e.g. {"Restaurants": [...]}
        if isinstance(data, dict) and "results" not in data:
            rows = [row for group in data.values() if isinstance(group, list) for row in group]
        else:
            rows = results(data)
        return [Bookmark.model_validate(r) for r in rows]

    return Request(
        "GET",
        "/api/get-bookmark/",
        params={"user": user_param(user), "category": category},
        parse=parse,
    )


# Guides


def guides(user: str | None) -> Request[list[Guide]]:
    return Request(
        "GET",
        "/api/user-guide/",
        params={"user_id": user_param(user), **GUIDE_FLAGS},
        parse=list_of(Guide),
    )


def guide_items(user: str | None) -> Request[list[GuideItem]]:
    return Request(
        "GET",
        "/api/user-guide-items/",
        params={"user_id": user_param(user), **GUIDE_FLAGS},
        parse=list_of(GuideItem),
    )


def guide(guide_id: int) -> Request[Any]:
    return Request(
        "GET",
        "/api/user-guide-list-view/",
        params={
            "list_id": guide_id,
            "viewer": ME,
            "check_user_access": "false",
            "playlists_v2": "true",
            "vguides": "true",
            **GUIDE_FLAGS,
        },
    )


# Social


def followers(user: str | None) -> Request[list[User]]:
    return Request(
        "GET",
        f"/api/followers/{user_param(user)}/",
        params={"include_followed": "true"},
        parse=list_of(User),
    )


def following(user: str | None) -> Request[list[User]]:
    return Request(
        "GET",
        f"/api/following/{user_param(user)}/",
        params={"include_followed": "true"},
        parse=list_of(User),
    )


# Places


def search(
    term: str, city: str | None, coords: tuple[float, float] | None
) -> Request[list[SearchResult]]:
    params: dict[str, Any] = {"term": term, "user": ME}
    if city:
        params["city"] = city
    if coords:
        params["coords"] = f"{coords[0]},{coords[1]}"
    return Request("GET", "/api/search-app/", params=params, parse=list_of(SearchResult))


def business_hours(business_id: int) -> Request[list[BusinessHours]]:
    return Request(
        "GET",
        "/api/business-hours/",
        params={"business": business_id},
        parse=list_of(BusinessHours),
    )


def trending(category: str) -> Request[list[Any]]:
    from .models import Business

    return Request(
        "GET", f"/api/trending/{ME}/", params={"category": category}, parse=list_of(Business)
    )


def raw_get(path: str, params: dict[str, Any] | None, host: str | None) -> Request[Any]:
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"  # Django APPEND_SLASH: routes need the trailing slash
    path = path.replace("{me}", ME)
    if params:
        params = {k: ME if v == "{me}" else v for k, v in params.items()}
    if host:
        return Request("GET", path, params=params, host=host)
    return Request("GET", path, params=params)
