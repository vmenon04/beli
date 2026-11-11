"""Token refresh in the sync client when several threads share one ``Beli``."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import respx

from beli import Beli
from beli._constants import HOST_API, HOST_ONBOARD

from .conftest import make_jwt

THREADS = 8


def _slow_refresh(api: respx.MockRouter, new_access: str) -> respx.Route:
    def refresh(request: httpx.Request) -> httpx.Response:
        threading.Event().wait(0.05)  # give the other threads time to pile up
        return httpx.Response(200, json={"access": new_access})

    route = api.post(f"{HOST_ONBOARD}/api/token/refresh/")
    route.side_effect = refresh
    return route


def _hammer(beli: Beli) -> list[object]:
    start = threading.Barrier(THREADS)

    def work() -> object:
        start.wait()
        return beli.photos.list()

    with ThreadPoolExecutor(THREADS) as pool:
        return [f.result() for f in [pool.submit(work) for _ in range(THREADS)]]


def test_expired_token_is_refreshed_once_across_threads(api: respx.MockRouter) -> None:
    new_access = make_jwt(900)
    refresh = _slow_refresh(api, new_access)
    beli = Beli(
        access_token=make_jwt(-10),
        refresh_token=make_jwt(3600, kind="refresh"),
        min_interval=0,
        discover_hosts=False,
    )
    assert len(_hammer(beli)) == THREADS
    assert refresh.call_count == 1
    photos = [c.request for c in api.calls if c.request.url.path.endswith("photos/")]
    assert {r.headers["Authorization"] for r in photos} == {f"Bearer {new_access}"}


def test_rejected_token_is_refreshed_once_across_threads(api: respx.MockRouter) -> None:
    # Not expired by the clock, but the server refuses it (revoked, clock skew).
    old_access, new_access = make_jwt(600), make_jwt(900)
    refresh = _slow_refresh(api, new_access)

    all_sent = threading.Barrier(THREADS)

    def photos(request: httpx.Request) -> httpx.Response:
        if request.headers["Authorization"] == f"Bearer {old_access}":
            all_sent.wait(timeout=5)  # every thread is refused with the same token
            return httpx.Response(401)
        return httpx.Response(200, json={"results": []})

    api.get(f"{HOST_API}/api/user-business-photos/").side_effect = photos
    refresh_token = make_jwt(3600, kind="refresh")
    beli = Beli(
        access_token=old_access, refresh_token=refresh_token, min_interval=0, discover_hosts=False
    )
    assert _hammer(beli) == [[]] * THREADS
    assert refresh.call_count == 1
    assert (beli.tokens.access, beli.tokens.refresh) == (new_access, refresh_token)
