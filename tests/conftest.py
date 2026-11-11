from __future__ import annotations

import base64
import json
import time
from collections.abc import Iterator
from typing import Any

import pytest
import respx

from beli._constants import HOST_API, HOST_ONBOARD, HOST_RECS

USER_ID = "bd6fbeef-31f0-4836-9199-69836572e74c"


def make_jwt(lifetime: float = 1200, user_id: str = USER_ID, kind: str = "access") -> str:
    def b64(obj: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    claims = {"token_type": kind, "exp": int(time.time() + lifetime), "user_id": user_id}
    return f"{b64({'alg': 'HS256', 'typ': 'JWT'})}.{b64(claims)}.sig"


def business(id: int, name: str, **kw: Any) -> dict[str, Any]:
    return {
        "id": id,
        "place_id": f"ChIJ{id}",
        "name": name,
        "status": "ACTIVE",
        "city": "Durham, NC",
        "borough": None,
        "lat": 35.99,
        "lng": -78.9,
        "price": 2,
        "neighborhood": "Downtown",
        "country": "United States",
        "website": f"https://example.com/{id}",
        "phone_number": "+19195550100",
        "cuisines": ["Thai"],
        "quick_link": f"https://beliapp.co/app/{id}",
        "businessdistinction_set": [],
        **kw,
    }


USER = {
    "id": USER_ID,
    "first_name": "Vasu",
    "last_name": "M",
    "full_name": "Vasu M",
    "username": "vasu",
    "created_dt": "2024-02-01T12:00:00Z",
    "profile_photo": "https://photos2.beliapp.cloud/p.jpg",
    "public": True,
    "lock_scores": False,
}

RANKINGS_RES = {
    "results": [
        {
            "id": 101,
            "user": USER_ID,
            "business": business(1, "Mateo"),
            "value": 2.5,
            "category": "RES",
            "created_dt": "2025-05-01T20:00:00Z",
            "visit_dates": ["2025-04-30", "2025-01-02"],
            "latest_visit_date": "2025-04-30",
            "score": 8.4,
        },
        {
            "id": 102,
            "user": USER_ID,
            "business": business(2, "Pizzeria Toro", cuisines=["Pizza", "Italian"]),
            "value": 2.5,
            "category": "RES",
            "created_dt": "2025-06-01T20:00:00Z",
            "visit_dates": [],
            "latest_visit_date": None,
            "score": 9.6,
        },
    ]
}

RANKINGS_BAR = {
    "results": [
        {
            "id": 201,
            "business": business(3, "Arcana"),
            "category": "BAR",
            "score": 7.1,
            "visit_dates": [{"visit_date": "2025-03-03"}],
        }
    ]
}

NOTES = {
    "count": 2,
    "next": None,
    "previous": None,
    "results": [
        {
            "id": 1,
            "start_dt": "2025-05-01T20:01:00Z",
            "end_dt": None,
            "value": "Get the tapas",
            "field": 11,
            "user": USER_ID,
            "business": 1,
            "visit": None,
        },
        {
            "id": 2,
            "start_dt": "2024-05-01T20:01:00Z",
            "end_dt": "2025-01-01T00:00:00Z",
            "value": "old note",
            "field": 11,
            "user": USER_ID,
            "business": 2,
            "visit": None,
        },
    ],
}

PHOTOS = {
    "results": [
        {
            "id": 9,
            "image": "https://photos2.beliapp.cloud/a.jpg",
            "thumbnail": None,
            "bb_image": None,
            "bb_thumbnail": None,
            "description": "",
            "order": 0,
            "favorite_dish": False,
            "created_dt": "2025-05-01T20:00:00Z",
            "status": "ACTIVE",
            "likes": [],
            "user": USER_ID,
            "business": 1,
        }
    ]
}

BOOKMARKS = {
    "Restaurants": [
        {
            "id": 55,
            "user": USER_ID,
            "business": business(4, "Lucky's"),
            "category": "RES",
            "start_dt": "2025-07-07T00:00:00Z",
        }
    ]
}

SETTINGS = {
    "results": [],
    "categories": [
        {"code": "RES", "display": "Restaurants", "icon": "x", "singular": "Restaurant"},
        {"code": "BAR", "display": "Bars", "icon": "y", "singular": "Bar"},
    ],
}

GUIDES = {
    "results": [
        {
            "id": 7,
            "name": "Date night",
            "full_title": "Date night in Durham",
            "audience": "PRIVATE",
            "is_draft": False,
            "categories": [],
            "cities": [],
        }
    ]
}
GUIDE_ITEMS = {"results": [{"business": 1, "guide": 7, "added_by": {"id": USER_ID}}]}
AVERAGES = {
    "COUNTRY": [{"count": 3, "score": 8.0, "value": "United States"}],
    "CITY": [{"count": 3, "score": 8.0, "value": "Durham, NC"}],
    "CUISINE": [{"value": "Thai", "count": 1, "score": 8.4}],
}

API_HOSTS = {
    "apiHost": HOST_API,
    "priorityHost": HOST_API,
    "profileHost": HOST_API,
    "photoHost": HOST_API,
    "recsHost": HOST_RECS,
    "activityHost": HOST_API,
    "popupsHost": HOST_API,
    "aiSearchHost": HOST_API,
    "defaultRetriesGet": 3,
    "defaultRetriesPost": 0,
    "defaultRetriesPut": 0,
}


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    for var in ("BELI_EMAIL", "BELI_PHONE", "BELI_PASSWORD", "BELI_REFRESH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("BELI_SESSION_FILE", str(tmp_path / "session.json"))
    monkeypatch.setattr("time.sleep", lambda s: None)


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{HOST_ONBOARD}/api/token/").respond(
            json={"access": make_jwt(), "refresh": make_jwt(7 * 86400, kind="refresh")}
        )
        router.post(f"{HOST_ONBOARD}/api/token/refresh/").respond(json={"access": make_jwt()})
        router.get(f"{HOST_ONBOARD}/api/user/logged-in/").respond(
            json={"count": 1, "results": [USER]}
        )
        router.get(f"{HOST_API}/api/api-hosts/").respond(json=API_HOSTS)
        router.get(f"{HOST_API}/api/user-setting/").respond(json=SETTINGS)
        router.get(f"{HOST_API}/api/get-ranking/", params={"category": "RES"}).respond(
            json=RANKINGS_RES
        )
        router.get(f"{HOST_API}/api/get-ranking/", params={"category": "BAR"}).respond(
            json=RANKINGS_BAR
        )
        router.get(f"{HOST_API}/api/datauserbusinesstext-sparse/").respond(json=NOTES)
        router.get(f"{HOST_API}/api/user-business-photos/").respond(json=PHOTOS)
        router.get(f"{HOST_API}/api/get-bookmark/", params={"category": "RES"}).respond(
            json=BOOKMARKS
        )
        router.get(f"{HOST_API}/api/get-bookmark/", params={"category": "BAR"}).respond(
            json={"Bars": []}
        )
        router.get(f"{HOST_API}/api/user-guide/").respond(json=GUIDES)
        router.get(f"{HOST_API}/api/user-guide-items/").respond(json=GUIDE_ITEMS)
        router.get(f"{HOST_API}/api/score-average/{USER_ID}/ALL/").respond(json=AVERAGES)
        router.get(f"{HOST_API}/api/user-field-count/{USER_ID}/RANK/").respond(json=2)
        yield router
