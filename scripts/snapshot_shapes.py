"""Record or check the shape of every response the exporter reads.

    python scripts/snapshot_shapes.py            # rewrite tests/shapes/*.json
    python scripts/snapshot_shapes.py --check    # compare, exit 1 on any difference

This talks to the live Beli API with the session saved by ``beli login`` (or
the BELI_* environment variables). It only reads. A shape is the set of JSON
paths in a response and the JSON types seen at each one: field names and
types, never values. Nothing else about a response is printed or stored.

Shapes depend on the account's data (an empty list has no element fields, a
field that is always null is only ever "null"), so record and check with the
same account.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from _drift import diff_shapes, exporter_calls, merge, shape_of
from beli import Beli, BeliError
from beli._auth import default_session_path

ROOT = Path(__file__).resolve().parent.parent
SHAPES = ROOT / "tests" / "shapes"

Entries = dict[str, dict[str, Any]]
"""File stem to ``{"endpoint": "GET /api/...", "shape": {...}}``."""


def collect(beli: Beli, categories: list[str] | None) -> tuple[Entries, list[str], bool]:
    """Returns the shapes, a list of problems, and whether the run was cut short."""
    shapes: Entries = {}
    problems: list[str] = []
    cut_short = False
    for capture in exporter_calls(beli, categories):
        if capture.error:
            problems.append(f"{capture.label}: {capture.error}")
        cut_short = cut_short or capture.fatal
        if capture.error and capture.raw is None:
            continue
        shape = shape_of(capture.raw)
        if capture.name in shapes:
            shape = merge(shapes[capture.name]["shape"], shape)
        shapes[capture.name] = {"endpoint": capture.label, "shape": shape}
    return shapes, problems, cut_short


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
    parser.add_argument("--session", default=str(default_session_path()), help="session file")
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
        with Beli.from_session(args.session, min_interval=args.interval) as beli:
            shapes, problems, cut_short = collect(beli, categories)
    except BeliError as exc:
        # The message of an API error quotes the response, so name the type only.
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
