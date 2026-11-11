from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path

import httpx
import pytest
import respx

from beli import (
    AsyncBeli,
    AuthenticationError,
    BadRequestError,
    Beli,
    BeliError,
    RateLimitError,
    ServerError,
    UnexpectedResponseError,
)
from beli._constants import HOST_API, HOST_ONBOARD

from .conftest import USER_ID, business, make_jwt


def client(**kw: object) -> Beli:
    return Beli("me@example.com", "pw", min_interval=0, **kw)  # type: ignore[arg-type]


def test_login_sends_required_headers(api: respx.MockRouter) -> None:
    with client() as beli:
        assert beli.me().username == "vasu"
    login = api.calls[0].request
    assert login.url == f"{HOST_ONBOARD}/api/token/"
    assert json.loads(login.content) == {"email": "me@example.com", "password": "pw"}
    me = api.calls[1].request
    assert me.headers["Origin"] == "capacitor://localhost"
    assert "Mozilla" in me.headers["User-Agent"]
    assert me.headers["Authorization"].startswith("Bearer ")


def test_phone_login(api: respx.MockRouter) -> None:
    Beli(phone="+15550100", password="pw", min_interval=0).login()
    assert json.loads(api.calls[0].request.content) == {"phone_no": "+15550100", "password": "pw"}


def test_user_id_is_filled_into_path_and_params(api: respx.MockRouter) -> None:
    with client() as beli:
        assert beli.rankings.count() == 2
        beli.rankings.list("RES")
    ranking_call = api.calls[-1].request
    assert ranking_call.url.params["user"] == USER_ID
    assert beli.user_id == USER_ID


def test_explicit_user_is_used_instead_of_own_id(api: respx.MockRouter) -> None:
    other = "11111111-2222-4333-8444-555555555555"
    route = api.get(f"{HOST_API}/api/user-field-count/{other}/RANK/").respond(json=5)
    with client() as beli:
        assert beli.rankings.count(user=other) == 5
        beli.rankings.list("RES", user=other)
    assert route.called
    assert api.calls[-1].request.url.params["user"] == other


def test_endpoint_builders_are_pure() -> None:
    from beli import _endpoints as ep

    request = ep.rankings("someone", "BAR")
    assert request.params == {"user": "someone", "category": "BAR"}
    assert ep.score_averages("someone").path == "/api/score-average/someone/ALL/"
    raw = ep.raw_get("someone", "api/x/{me}", {"user": "{me}", "q": "{me} too"}, None)
    assert (raw.path, raw.params) == ("/api/x/someone/", {"user": "someone", "q": "{me} too"})


def test_rankings_keep_api_order_by_default(api: respx.MockRouter) -> None:
    with client() as beli:
        rankings = beli.rankings.list()
    assert [r.business.name for r in rankings] == ["Mateo", "Pizzeria Toro"]
    mateo = rankings[0]
    assert mateo.visit_dates[0].isoformat() == "2025-04-30"
    assert mateo.business.price_symbol == "$$"
    assert mateo.business.model_extra == {"businessdistinction_set": []}


def test_rankings_sort_by_score_is_opt_in_and_stable(api: respx.MockRouter) -> None:
    def row(id: int, score: float | None) -> dict[str, object]:
        return {"id": id, "business": business(id, f"P{id}"), "category": "RES", "score": score}

    rows = [row(1, 7.0), row(2, 9.5), row(3, None), row(4, 9.5), row(5, 7.0)]
    api.get(f"{HOST_API}/api/get-ranking/", params={"category": "RES"}).respond(
        json={"results": rows}
    )
    with client() as beli:
        assert [r.id for r in beli.rankings.list()] == [1, 2, 3, 4, 5]
        assert [r.id for r in beli.rankings.list(sort="score")] == [2, 4, 1, 5, 3]
        assert [r.id for r in beli.rankings.all(["RES"], sort="score")] == [2, 4, 1, 5, 3]
        with pytest.raises(ValueError, match="Unknown sort"):
            beli.rankings.list(sort="name")  # type: ignore[arg-type]


def test_all_rankings_uses_account_categories(api: respx.MockRouter) -> None:
    with client() as beli:
        rankings = beli.rankings.all()
    assert {r.category for r in rankings} == {"RES", "BAR"}
    bar = next(r for r in rankings if r.category == "BAR")
    assert [d.isoformat() for d in bar.visit_dates] == ["2025-03-03"]


def test_notes_skip_closed_entries(api: respx.MockRouter) -> None:
    with client() as beli:
        notes = beli.notes.list()
        assert [n.text for n in notes] == ["Get the tapas"]
        assert beli.notes.get(1) == "Get the tapas"
        assert beli.notes.get(2) is None
    assert api.calls[-1].request.url.params["field__name"] == "NOTES"


def test_bookmarks_keyed_by_display_name(api: respx.MockRouter) -> None:
    with client() as beli:
        (bm,) = beli.bookmarks.list()
    assert bm.business.name == "Lucky's"


def test_expired_access_is_refreshed_not_relogged(api: respx.MockRouter) -> None:
    beli = Beli(
        access_token=make_jwt(-10), refresh_token=make_jwt(3600, kind="refresh"), min_interval=0
    )
    beli.me()
    paths = [c.request.url.path for c in api.calls]
    assert paths == ["/api/token/refresh/", "/api/user/logged-in/"]


def test_dead_refresh_falls_back_to_password(api: respx.MockRouter) -> None:
    api.post(f"{HOST_ONBOARD}/api/token/refresh/").respond(401, json={"detail": "Token is invalid"})
    beli = client(refresh_token=make_jwt(3600, kind="refresh"))
    beli.me()
    assert [c.request.url.path for c in api.calls][:2] == ["/api/token/refresh/", "/api/token/"]


def test_no_credentials_raises() -> None:
    with pytest.raises(AuthenticationError, match="beli login"):
        Beli(min_interval=0).me()


def test_bad_password(api: respx.MockRouter) -> None:
    api.post(f"{HOST_ONBOARD}/api/token/").respond(401, json={"detail": "No active account"})
    with pytest.raises(AuthenticationError, match="No active account"):
        client().login()


def test_401_triggers_one_refresh_and_retry(api: respx.MockRouter) -> None:
    route = api.get(f"{HOST_API}/api/user-business-photos/")
    route.side_effect = [httpx.Response(401), httpx.Response(200, json={"results": []})]
    with client() as beli:
        assert beli.photos.list() == []
    assert route.call_count == 2


def test_429_is_retried_with_retry_after(
    api: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    slept: list[float] = []
    monkeypatch.setattr("time.sleep", slept.append)
    route = api.get(f"{HOST_API}/api/user-business-photos/")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(200, json={"results": []}),
    ]
    client().photos.list()
    assert 7.0 in slept


def test_retries_give_up(api: respx.MockRouter) -> None:
    api.get(f"{HOST_API}/api/user-business-photos/").respond(503, text="busy")
    with pytest.raises(ServerError) as info:
        client(max_retries=2).photos.list()
    assert info.value.status_code == 503
    api.get(f"{HOST_API}/api/user-business-photos/").respond(429)
    with pytest.raises(RateLimitError):
        client(max_retries=0).photos.list()


def test_400_not_retried(api: respx.MockRouter) -> None:
    route = api.get(f"{HOST_API}/api/user-business-photos/").respond(400, text="Missing parameters")
    with pytest.raises(BadRequestError, match="Missing parameters"):
        client().photos.list()
    assert route.call_count == 1


def test_changed_response_raises_one_clear_error(api: respx.MockRouter) -> None:
    changed = {"id": 1, "business": "a-private-value", "picture": "https://example.com/1.jpg"}
    api.get(f"{HOST_API}/api/user-business-photos/").respond(200, json={"results": [changed]})
    with pytest.raises(UnexpectedResponseError) as info:
        client().photos.list()
    error = info.value
    assert isinstance(error, BeliError)
    assert (error.method, error.path) == ("GET", "/api/user-business-photos/")
    assert "0.business (int_parsing)" in error.problem
    assert "0.image (missing)" in error.problem
    assert "upgrade beli" in str(error)
    assert "a-private-value" not in str(error)
    assert error.__cause__ is not None

    # A parser that trips over the envelope itself is reported the same way.
    api.get(f"{HOST_API}/api/user/streak/").respond(200, json={"result": "soon"})
    with pytest.raises(UnexpectedResponseError) as info:
        client().users.streak()
    assert info.value.problem == "ValueError"
    assert "soon" not in str(info.value)


def test_changed_response_async(api: respx.MockRouter) -> None:
    api.get(f"{HOST_API}/api/user-business-photos/").respond(200, json={"results": [{}]})

    async def run() -> None:
        async with AsyncBeli("me@example.com", "pw", min_interval=0) as beli:
            await beli.photos.list()

    with pytest.raises(UnexpectedResponseError, match="does not validate"):
        asyncio.run(run())


def test_read_only(api: respx.MockRouter) -> None:
    from beli._session import Call, Request

    beli = client()
    for resource, name in [
        (beli.notes, "set"),
        (beli.bookmarks, "add"),
        (beli.bookmarks, "remove"),
        (beli.rankings, "delete"),
    ]:
        assert not hasattr(resource, name)
    with pytest.raises(ValueError, match="read-only"):
        beli._transport.send(Request("POST", "/api/add-bookmark/"))
    # The guard sits on the effect every request becomes, so nothing can go around it.
    for method, path, body in [
        ("POST", "/api/add-bookmark/", {}),
        ("DELETE", "/api/rank/1/", None),
        ("PUT", "/api/token/", {}),
        ("GET", "/api/get-ranking/", {"smuggled": "body"}),
    ]:
        with pytest.raises(ValueError, match="read-only"):
            Call(method, HOST_API + path, json=body)
    Call("POST", HOST_ONBOARD + "/api/token/refresh/", json={"refresh": "x"})
    assert not any(
        c.request.method != "GET" and "token" not in c.request.url.path for c in api.calls
    )


def test_raw_get(api: respx.MockRouter) -> None:
    route = api.get(f"{HOST_API}/api/user/streak/").respond(json={"result": 4})
    data = client().get("api/user/streak", params={"user": "{me}"})
    assert data == {"result": 4}
    assert route.calls[0].request.url.params["user"] == USER_ID


def test_session_file_saved_private_and_resumed(api: respx.MockRouter, tmp_path: Path) -> None:
    path = tmp_path / "s" / "session.json"
    client(session_file=path).login()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    saved = json.loads(path.read_text())
    assert set(saved) == {"access", "refresh"}
    assert "pw" not in path.read_text()

    before = len(api.calls)
    Beli.from_session(path, min_interval=0).me()
    assert [c.request.url.path for c in api.calls][before:] == ["/api/user/logged-in/"]


def test_env_refresh_token(api: respx.MockRouter, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELI_REFRESH_TOKEN", make_jwt(3600, kind="refresh"))
    Beli(min_interval=0).me()
    assert api.calls[0].request.url.path == "/api/token/refresh/"


async def test_async_client(api: respx.MockRouter) -> None:
    async with AsyncBeli("me@example.com", "pw", min_interval=0) as beli:
        rankings = await beli.rankings.all()
        assert len(rankings) == 3
        assert await beli.notes.get(1) == "Get the tapas"
        assert await beli.user_id() == USER_ID
        export = await beli.export()
    assert len(export.rated_places()) == 3


async def test_async_transport_retries_and_reauths(
    api: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    route = api.get(f"{HOST_API}/api/user-business-photos/")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(401),
        httpx.ConnectError("down"),
        httpx.Response(200, json={"results": []}),
    ]
    async with AsyncBeli("me@example.com", "pw", min_interval=0) as beli:
        assert await beli.photos.list() == []
    assert route.call_count == 4
    assert slept == [7.0, 4.0]
    assert [c.request.url.path for c in api.calls].count("/api/token/refresh/") == 1
