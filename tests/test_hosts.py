from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from beli import AsyncBeli, Beli
from beli._constants import FALLBACK_HOSTS, HOST_API, HOST_ONBOARD, HOST_RECS
from beli._transport import parse_hosts

NEW_API = "https://api.beli.example"
HOSTS_URL = f"{HOST_API}/api/api-hosts/"


def client(**kw: Any) -> Beli:
    return Beli("me@example.com", "pw", min_interval=0, **kw)


def test_discovered_host_is_used_and_asked_for_once(api: respx.MockRouter) -> None:
    hosts = api.get(HOSTS_URL).respond(json={"apiHost": NEW_API, "recsHost": "recs.beli.example"})
    photos = api.get(f"{NEW_API}/api/user-business-photos/").respond(json={"results": []})
    notes = api.get(f"{NEW_API}/api/datauserbusinesstext-sparse/").respond(json={"results": []})
    recs = api.get("https://recs.beli.example/api/anything/").respond(json={})
    with client() as beli:
        beli.photos.list()
        beli.notes.list()
        beli.get("/api/anything/", host="recs")
    assert (hosts.call_count, photos.call_count, notes.call_count, recs.call_count) == (1, 1, 1, 1)
    assert hosts.calls[0].request.headers["Authorization"].startswith("Bearer ")


def test_login_and_me_do_not_need_discovery(api: respx.MockRouter) -> None:
    hosts = api.get(HOSTS_URL)
    with client() as beli:
        beli.login()
        beli.me()
    assert not hosts.called
    assert {c.request.url.host for c in api.calls} == {httpx.URL(HOST_ONBOARD).host}


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(500, text="oops"),
        httpx.Response(401),
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json=["unexpected"]),
        httpx.Response(200, json={"apiHost": "http://plain.example"}),
        httpx.Response(200, json={"apiHost": 7, "recsHost": ""}),
        httpx.ConnectError("down"),
    ],
)
def test_any_discovery_failure_falls_back(api: respx.MockRouter, answer: Any) -> None:
    hosts = api.get(HOSTS_URL)
    hosts.side_effect = [answer]
    with client() as beli:
        assert beli.rankings.count() == 2
        assert beli.rankings.count() == 2
    assert hosts.call_count == 1  # not retried, and not asked again
    assert beli._transport.hosts == FALLBACK_HOSTS


def test_discovery_can_be_turned_off(api: respx.MockRouter) -> None:
    hosts = api.get(HOSTS_URL)
    with client(discover_hosts=False) as beli:
        assert beli.rankings.count() == 2
    assert not hosts.called


def test_full_url_host_is_used_as_given(api: respx.MockRouter) -> None:
    route = api.get("https://other.example/api/thing/").respond(json={"ok": True})
    hosts = api.get(HOSTS_URL)
    assert client().get("/api/thing/", host="https://other.example/") == {"ok": True}
    assert route.called and not hosts.called


async def test_async_discovers_once_under_concurrency(api: respx.MockRouter) -> None:
    import asyncio

    hosts = api.get(HOSTS_URL).respond(json={"apiHost": NEW_API})
    api.get(f"{NEW_API}/api/user-business-photos/").respond(json={"results": []})
    async with AsyncBeli("me@example.com", "pw", min_interval=0) as beli:
        await asyncio.gather(*(beli.photos.list() for _ in range(5)))
    assert hosts.call_count == 1


def test_parse_hosts() -> None:
    assert parse_hosts({"apiHost": "a.example", "recsHost": "https://r.example/", "x": 1}) == {
        "api": "https://a.example",
        "recs": "https://r.example",
    }
    assert parse_hosts({"apiHost": "https://a.example/some/path"}) == {}
    assert parse_hosts({"apiHost": "ftp://a.example"}) == {}
    assert parse_hosts({"apiHost": "https://"}) == {}
    assert parse_hosts(None) == {}
    assert parse_hosts({"onboardingHost": "https://evil.example"}) == {}
    assert FALLBACK_HOSTS["recs"] == HOST_RECS
