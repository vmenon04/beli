"""Shared by the drift scripts: capture the exporter's responses and describe their shape.

Nothing here prints or stores a response value. Shapes hold field names and
JSON types only, and errors are described without the response body.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any

from pydantic import ValidationError

from beli import Beli
from beli import _plans as plans
from beli._constants import HOSTS_PATH
from beli._session import Request
from beli.errors import APIError, UnexpectedResponseError, describe_parse_failure

Shape = dict[str, list[str]]
"""JSON path to the sorted JSON types seen there, e.g. ``{"$.results[].id": ["number"]}``."""

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def _raw(data: Any) -> Any:
    return data


def _type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        # 8 and 8.0 are the same JSON number; which one arrives depends on the data.
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise TypeError(f"not a JSON value: {type(value).__name__}")


def _key(key: str) -> str:
    """Field names are kept. Keys that are data (ids used as map keys) become ``*``."""
    return "*" if key.isdigit() or _UUID.fullmatch(key) else key


def shape_of(data: Any) -> Shape:
    """Flatten a JSON value into path -> types. Array elements are merged under ``[]``."""
    seen: dict[str, set[str]] = {}

    def walk(value: Any, path: str) -> None:
        seen.setdefault(path, set()).add(_type(value))
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}.{_key(str(key))}")
        elif isinstance(value, list):
            for item in value:
                walk(item, f"{path}[]")

    walk(data, "$")
    return {path: sorted(types) for path, types in sorted(seen.items())}


def merge(a: Shape, b: Shape) -> Shape:
    return {path: sorted({*a.get(path, []), *b.get(path, [])}) for path in sorted({*a, *b})}


def shape_lines(shape: Shape) -> list[str]:
    return [f"{path}: {' | '.join(types)}" for path, types in shape.items()]


def diff_shapes(old: Shape, new: Shape, name: str) -> list[str]:
    """Unified diff of two shapes, empty if they are the same."""
    return list(
        difflib.unified_diff(
            shape_lines(old),
            shape_lines(new),
            f"stored/{name}",
            f"live/{name}",
            lineterm="",
            n=1,
        )
    )


def label(request: Request[Any], me: str) -> str:
    """``GET /api/score-average/{user}/ALL/``: the path with the account's id masked."""
    return f"{request.method} {request.path.replace(me, '{user}')}"


def slug(request: Request[Any], me: str) -> str:
    """File stem for an endpoint: ``score-average.USER.ALL``."""
    path = request.path.replace(me, "USER").removeprefix("/api/").strip("/")
    return path.replace("/", ".")


def describe(exc: BaseException, me: str = "") -> str:
    """Say what went wrong without quoting any of the response."""
    if isinstance(exc, APIError):
        request = exc.response.request
        # Mask the account's id, and any other id in the path, before it is printed.
        path = _UUID.sub("{user}", request.url.path.replace(me or "\0", "{user}"))
        return f"HTTP {exc.status_code} from {request.method} {path}"
    if isinstance(exc, UnexpectedResponseError):
        return exc.problem
    if isinstance(exc, ValidationError):
        return describe_parse_failure(exc)
    return type(exc).__name__


@dataclass
class Capture:
    """One request the exporter made and what came back."""

    name: str
    label: str
    request: Request[Any]
    raw: Any = None
    error: str | None = None
    fatal: bool = False


def exporter_calls(beli: Beli, categories: list[str] | None = None) -> Iterator[Capture]:
    """Run the export plan against ``beli`` and yield every response, unparsed.

    This drives the same plan ``Beli.export()`` runs, so it calls exactly the
    endpoints the exporter uses, plus host discovery. A capture with ``fatal``
    set is the last one: the exporter could not have gone on from there.
    """
    me = beli.user_id
    transport = beli._transport

    hosts: Request[Any] = Request("GET", HOSTS_PATH)
    capture = Capture(slug(hosts, me), label(hosts, me), hosts)
    try:
        capture.raw = transport.send(hosts)
    except APIError as exc:
        capture.error = describe(exc, me)
    yield capture

    plan = plans.export(me, categories, None)
    result: Any = None
    error: APIError | None = None
    while True:
        try:
            request = plan.throw(error) if error is not None else plan.send(result)
        except StopIteration:
            return
        except APIError:
            # A part the exporter cannot do without failed. It was reported
            # on the capture yielded just before this.
            return
        result, error = None, None
        capture = Capture(slug(request, me), label(request, me), request)
        try:
            capture.raw = transport.send(replace(request, parse=_raw))
            result = request.parse(capture.raw)
        except APIError as exc:
            capture.error = describe(exc, me)
            error = exc
        except Exception as exc:
            capture.error = f"response no longer parses: {describe(exc, me)}"
            capture.fatal = True
        yield capture
        if capture.fatal:
            return


def replay_export(fixtures: dict[str, dict[str, Any]]) -> Any:
    """Run the export plan against recorded fixtures instead of the network.

    ``fixtures`` maps file stems to the entries ``record_fixtures.py`` writes.
    Returns the :class:`beli.Export`. A request with no fixture is a ``KeyError``.
    """
    me = fixtures["user.logged-in"]["response"]["results"][0]["id"]
    plan = plans.export(me, None, None)
    result: Any = None
    while True:
        try:
            request = plan.send(result)
        except StopIteration as stop:
            return stop.value
        category = (request.params or {}).get("category")
        name = slug(request, me) + (f".{category}" if category else "")
        result = request.parse(fixtures[name]["response"])
