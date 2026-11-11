"""Record or check the shape of every response the exporter reads.

    python scripts/snapshot_shapes.py            # rewrite tests/shapes/*.json
    python scripts/snapshot_shapes.py --check    # compare, exit 1 on any difference

This talks to the live Beli API with the session saved by ``beli login`` (or
the BELI_* environment variables). It only reads: it runs ``Beli.export()``
and looks at each response on the way past.

A shape is the set of JSON paths in a response and the JSON types seen at
each one: field names and types, never values. Nothing else about a response
is printed or stored.

Shapes depend on the account's data (an empty list has no element fields, a
field that is always null is only ever "null"), so record and check with the
same account.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx

from beli import APIError, Beli, BeliError, UnexpectedResponseError

ROOT = Path(__file__).resolve().parent.parent
SHAPES = ROOT / "tests" / "shapes"

Shape = dict[str, list[str]]
"""JSON path to the sorted JSON types seen there, e.g. ``{"$.results[].id": ["number"]}``."""

Entries = dict[str, dict[str, Any]]
"""File stem to ``{"endpoint": "GET /api/...", "shape": {...}}``."""

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


# Shapes


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


def shape_of(data: Any) -> Shape:
    """Flatten a JSON value into path -> types. Array elements are merged under ``[]``."""
    seen: dict[str, set[str]] = {}

    def walk(value: Any, path: str) -> None:
        seen.setdefault(path, set()).add(_type(value))
        if isinstance(value, dict):
            for key, item in value.items():
                # Field names are kept. Keys that are data (ids used as map keys) become ``*``.
                name = "*" if key.isdigit() or _UUID.fullmatch(key) else key
                walk(item, f"{path}.{name}")
        elif isinstance(value, list):
            for item in value:
                walk(item, f"{path}[]")

    walk(data, "$")
    return {path: sorted(types) for path, types in sorted(seen.items())}


def merge(a: Shape, b: Shape) -> Shape:
    return {path: sorted({*a.get(path, []), *b.get(path, [])}) for path in sorted({*a, *b})}


def diff_shapes(old: Shape, new: Shape, name: str) -> list[str]:
    """Unified diff of two shapes, empty if they are the same."""

    def lines(shape: Shape) -> list[str]:
        return [f"{path}: {' | '.join(types)}" for path, types in shape.items()]

    return list(
        difflib.unified_diff(
            lines(old), lines(new), f"stored/{name}", f"live/{name}", lineterm="", n=1
        )
    )


# Saying what happened without quoting a response


def _mask(path: str) -> str:
    """A request path with every user id replaced, so it is safe to publish."""
    return _UUID.sub("{user}", path)


def describe(exc: BaseException) -> str:
    """Say what went wrong without quoting any of the response.

    ``str()`` of an ``APIError`` includes the response body, so reports that
    are printed in CI or posted to an issue use this instead.
    """
    if isinstance(exc, APIError):
        request = exc.response.request
        return f"HTTP {exc.status_code} from {request.method} {_mask(request.url.path)}"
    if isinstance(exc, UnexpectedResponseError):
        return f"{exc.method} {_mask(exc.path)}: {exc.problem}"
    return type(exc).__name__


# Running the export and collecting shapes


def collect(
    session: str | None, interval: float, categories: list[str] | None
) -> tuple[Entries, list[str], bool]:
    """Run an export. Returns the shapes, a list of problems, and whether it was cut short."""
    shapes: Entries = {}
    failed: dict[str, str] = {}  # URL to problem, removed again if a retry succeeds

    def look(response: httpx.Response) -> None:
        request = response.request
        if request.method != "GET":
            return  # login and token refresh
        url, path = str(request.url), _mask(request.url.path)
        endpoint = f"GET {path}"
        if response.status_code != 200:
            failed[url] = f"{endpoint}: HTTP {response.status_code}"
            return
        failed.pop(url, None)
        response.read()
        try:
            shape = shape_of(response.json() if response.content else None)
        except ValueError:
            failed[url] = f"{endpoint}: the response is not JSON"
            return
        name = path.removeprefix("/api/").strip("/").replace("/", ".").replace("{user}", "USER")
        if name in shapes:
            shape = merge(shapes[name]["shape"], shape)
        shapes[name] = {"endpoint": endpoint, "shape": shape}

    cut_short = False
    http = httpx.Client(timeout=30, event_hooks={"response": [look]})
    with http, Beli.from_session(session, min_interval=interval, http_client=http) as beli:
        try:
            beli.export(categories)
        except (APIError, UnexpectedResponseError) as exc:
            # A part the exporter cannot do without failed, or no longer parses.
            cut_short = True
            if isinstance(exc, UnexpectedResponseError):
                failed["parse"] = f"response no longer parses: {describe(exc)}"
    return shapes, list(failed.values()), cut_short


def write(shapes: Entries, directory: Path) -> list[str]:
    directory.mkdir(parents=True, exist_ok=True)
    lines = []
    for name, entry in sorted(shapes.items()):
        (directory / f"{name}.json").write_text(json.dumps(entry, indent=2) + "\n")
        lines.append(f"wrote {name}.json ({len(entry['shape'])} paths)")
    for stale in sorted(directory.glob("*.json")):
        if stale.stem not in shapes:
            stale.unlink()
            lines.append(f"removed {stale.name} (the exporter no longer calls it)")
    return lines


def check(shapes: Entries, directory: Path, cut_short: bool) -> list[str]:
    """Markdown describing every difference from the stored shapes. Empty means none."""
    out: list[str] = []
    stored = {p.stem: json.loads(p.read_text()) for p in sorted(directory.glob("*.json"))}
    for name, entry in sorted(shapes.items()):
        if name not in stored:
            out += [f"### {entry['endpoint']}", "", f"No stored shape (`{name}.json`).", ""]
            continue
        diff = diff_shapes(stored[name]["shape"], entry["shape"], f"{name}.json")
        if diff:
            out += [f"### {entry['endpoint']}", "", "```diff", *diff, "```", ""]
    if not cut_short:
        for name in sorted(set(stored) - set(shapes)):
            out += [f"### {stored[name]['endpoint']}", "", "Stored, but no response this run.", ""]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="compare instead of writing")
    parser.add_argument("--session", help="session file (default: the one `beli login` wrote)")
    parser.add_argument("--interval", type=float, default=2.0, help="seconds between requests")
    parser.add_argument("--categories", help="comma-separated codes (default: the account's)")
    parser.add_argument("--dir", type=Path, default=SHAPES, help="where the shapes live")
    parser.add_argument("--report", type=Path, help="also write the result here as Markdown")
    args = parser.parse_args(argv)
    categories = (
        [c.strip().upper() for c in args.categories.split(",")] if args.categories else None
    )

    report: list[str] = []
    try:
        shapes, problems, cut_short = collect(args.session, args.interval, categories)
    except BeliError as exc:
        report = [f"Could not read the API: {type(exc).__name__}"]
        failed = True
    else:
        if problems:
            report += ["### Requests that failed", "", *[f"- {p}" for p in problems], ""]
        if cut_short:
            report += ["The run stopped early, so later endpoints were not checked.", ""]
        if args.check:
            report += check(shapes, args.dir, cut_short)
            failed = bool(report)
            if not failed:
                report = [f"{len(shapes)} response shapes match."]
        else:
            failed = bool(problems)
            report += write(shapes, args.dir)

    text = "\n".join(report).rstrip() + "\n"
    print(text, end="")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
