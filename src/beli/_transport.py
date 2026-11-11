"""The two transports: the only code that sleeps, locks or talks to the network.

Each one carries out the effects a :class:`~beli._session.Session` flow
yields. They differ only in how they wait.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, TypeVar

import httpx

from ._auth import Tokens
from ._session import Call, Config, Exclusive, Flow, Plan, Request, Session, Sleep

__all__ = ["AsyncTransport", "Config", "Request", "SyncTransport"]

T = TypeVar("T")


def _kwargs(call: Call) -> dict[str, Any]:
    return {
        "params": dict(call.params) if call.params is not None else None,
        "json": call.json,
        "headers": dict(call.headers),
    }


class SyncTransport:
    def __init__(self, config: Config, http: httpx.Client | None = None) -> None:
        self.config = config
        self.session = Session(config)
        self._owns_http = http is None
        self.http = http or httpx.Client(timeout=config.timeout)
        self._throttle_lock = threading.Lock()
        self._auth_lock = threading.Lock()
        self._last = 0.0

    def close(self) -> None:
        if self._owns_http:
            self.http.close()

    def login(self) -> Tokens:
        return self._perform(self.session.login())

    def user_id(self) -> str:
        return self._perform(self.session.user_id())

    def send(self, request: Request[T]) -> T:
        return self._perform(self.session.send(request))

    def run(self, plan: Plan[T]) -> T:
        return self._perform(self.session.run(plan))

    def _throttle(self) -> None:
        with self._throttle_lock:
            wait = self.config.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def _call(self, call: Call) -> httpx.Response | httpx.TransportError:
        self._throttle()
        try:
            return self.http.request(call.method, call.url, **_kwargs(call))
        except httpx.TransportError as exc:
            return exc

    def _perform(self, flow: Flow[T]) -> T:
        reply: Any = None
        failure: Exception | None = None
        while True:
            try:
                effect = flow.throw(failure) if failure is not None else flow.send(reply)
            except StopIteration as stop:
                value: T = stop.value
                return value
            reply, failure = None, None
            if isinstance(effect, Sleep):
                time.sleep(effect.seconds)
            elif isinstance(effect, Exclusive):
                try:
                    with self._auth_lock:
                        reply = self._perform(effect.flow)
                except Exception as exc:
                    failure = exc
            else:
                reply = self._call(effect)


class AsyncTransport:
    def __init__(self, config: Config, http: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self.session = Session(config)
        self._owns_http = http is None
        self.http = http or httpx.AsyncClient(timeout=config.timeout)
        self._throttle_lock = asyncio.Lock()
        self._auth_lock = asyncio.Lock()
        self._last = 0.0

    async def close(self) -> None:
        if self._owns_http:
            await self.http.aclose()

    async def login(self) -> Tokens:
        return await self._perform(self.session.login())

    async def user_id(self) -> str:
        return await self._perform(self.session.user_id())

    async def send(self, request: Request[T]) -> T:
        return await self._perform(self.session.send(request))

    async def run(self, plan: Plan[T]) -> T:
        return await self._perform(self.session.run(plan))

    async def _throttle(self) -> None:
        async with self._throttle_lock:
            wait = self.config.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()

    async def _call(self, call: Call) -> httpx.Response | httpx.TransportError:
        await self._throttle()
        try:
            return await self.http.request(call.method, call.url, **_kwargs(call))
        except httpx.TransportError as exc:
            return exc

    async def _perform(self, flow: Flow[T]) -> T:
        reply: Any = None
        failure: Exception | None = None
        while True:
            try:
                effect = flow.throw(failure) if failure is not None else flow.send(reply)
            except StopIteration as stop:
                value: T = stop.value
                return value
            reply, failure = None, None
            if isinstance(effect, Sleep):
                await asyncio.sleep(effect.seconds)
            elif isinstance(effect, Exclusive):
                try:
                    async with self._auth_lock:
                        reply = await self._perform(effect.flow)
                except Exception as exc:
                    failure = exc
            else:
                reply = await self._call(effect)
