"""Replace everything personal in a recorded response with fake values.

The rule for strings is deny by default: a string is replaced unless it sits
under a key known to hold an enum code (``category``, ``status``, ...) and
looks like one. So a field Beli adds tomorrow is scrubbed without anyone
having to list it here.

What is replaced:

* ids (numbers under id-like keys, any large integer, UUIDs, numeric strings),
  through one mapping so that the same real id always becomes the same fake
  id and joins between responses still work;
* names, note text, addresses, phone numbers and every other free string;
* URLs, coordinates, dates and times, tokens.

What is kept: field names, booleans, nulls, enum codes, and small numbers that
are not ids (scores, counts, prices, positions). Lists are cut to a few items.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

KEEP_KEYS = frozenset({"category", "default_category", "code", "status", "audience", "price_key"})
"""Keys whose values are app-defined codes, kept when they look like one."""

ID_KEYS = frozenset(
    {"id", "business", "user", "guide", "field", "visit", "added_by", "list", "owner", "photo"}
)
COORD_KEYS = {"lat": 40.0, "latitude": 40.0, "lng": -74.0, "lon": -74.0, "longitude": -74.0}

FAKE_UUID = "00000000-0000-4000-8000-"
FAKE_URL = "https://example.com/"

_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,23}")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
_URL = re.compile(r"[a-z][a-z0-9+.-]*://", re.I)

# Things that must not appear anywhere in a scrubbed fixture.
_LEAKS = {
    "a URL that is not example.com": re.compile(r"[a-z][a-z0-9+.-]*://(?!example\.com/)", re.I),
    "a JWT": re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    "a real UUID": re.compile(
        rf"(?!{FAKE_UUID})[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}",
        re.I,
    ),
    "an email address": re.compile(r"[^\s@\"]+@[^\s@\"]+\.[a-z]{2,}", re.I),
}


def _is_id_key(key: str) -> bool:
    return key in ID_KEYS or key.endswith(("_id", "_ids"))


class Scrubber:
    """Scrubs any number of responses with one consistent set of fake values."""

    def __init__(self, max_items: int = 3) -> None:
        self.max_items = max_items
        self._ids: dict[int, int] = {}
        self._fakes: dict[tuple[str, str], str] = {}
        self._counts: dict[str, int] = {}
        self.originals: set[str] = set()

    def _fake(self, kind: str, value: str, make: Any) -> str:
        if (kind, value) not in self._fakes:
            n = self._counts[kind] = self._counts.get(kind, 0) + 1
            self._fakes[kind, value] = make(n)
        self.originals.add(value)
        return self._fakes[kind, value]

    def _id(self, value: int) -> int:
        return self._ids.setdefault(value, 1001 + len(self._ids))

    def _string(self, value: str, key: str) -> str:
        if not value:
            return value
        if key in KEEP_KEYS and _CODE.fullmatch(value):
            return value
        if _UUID.fullmatch(value):
            return self._fake("uuid", value.lower(), lambda n: f"{FAKE_UUID}{n:012d}")
        if _URL.match(value):
            return self._fake(f"url:{key}", value, lambda n: f"{FAKE_URL}{key or 'url'}/{n}")
        if _DATETIME.match(value):
            day = self._fake("date", value[:10], lambda n: str(date(2024, 1, 1) + timedelta(n)))
            return f"{day}T12:00:00Z"
        if _DATE.fullmatch(value):
            return self._fake("date", value, lambda n: str(date(2024, 1, 1) + timedelta(n)))
        if value.isdigit():
            return str(self._id(int(value)))
        return self._fake(f"text:{key}", value, lambda n: f"{key or 'text'}-{n}")

    def scrub(self, data: Any, key: str = "") -> Any:
        """A scrubbed copy of ``data``. ``key`` is the field name it was found under."""
        if data is None or isinstance(data, bool):
            return data
        if isinstance(data, str):
            return self._string(data, key)
        if isinstance(data, int):
            if key in COORD_KEYS:
                return COORD_KEYS[key]
            return self._id(data) if _is_id_key(key) or abs(data) >= 100_000 else data
        if isinstance(data, float):
            return COORD_KEYS.get(key, data)
        if isinstance(data, list):
            return [self.scrub(item, key) for item in data[: self.max_items]]
        if isinstance(data, dict):
            out = {}
            for name, item in data.items():
                name = str(name)
                # Keys that are data (a map keyed by id) are scrubbed like values.
                fake_name = (
                    self._string(name, "id") if _UUID.fullmatch(name) or name.isdigit() else name
                )
                out[fake_name] = self.scrub(item, name)
            return out
        raise TypeError(f"not a JSON value: {type(data).__name__}")

    def leaks(self, scrubbed: Any) -> list[str]:
        """Reasons ``scrubbed`` is not safe to commit. Describes, never quotes."""
        values: list[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, str):
                values.append(node)
            elif isinstance(node, list):
                for item in node:
                    walk(item)
            elif isinstance(node, dict):
                for item in node.values():
                    walk(item)

        walk(scrubbed)
        problems = pattern_leaks("\n".join(values))
        survivors = sum(
            1
            for original in self.originals
            if len(original) >= 4 and any(original in v for v in values)
        )
        if survivors:
            problems.append(f"{survivors} original value(s) survive in the output")
        return problems


def pattern_leaks(text: str) -> list[str]:
    """Checks that need no knowledge of the original: usable on fixtures already on disk."""
    return [f"contains {what}" for what, pattern in _LEAKS.items() if pattern.search(text)]
