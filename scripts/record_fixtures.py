"""Record the exporter's live responses as scrubbed test fixtures.

    python scripts/record_fixtures.py            # rewrite tests/fixtures/*.json

This talks to the live Beli API with the session saved by ``beli login`` (or
the BELI_* environment variables). It only reads. Every response is scrubbed
before it is written (see ``_scrub.py``): ids, names, coordinates, URLs,
dates, tokens and note text are replaced with fake values, and lists are cut
to ``--max-items``. Scores, counts and other small numbers are kept as they
are. Nothing is written if a request fails or if anything recognisable is
left after scrubbing.

Read ``git diff tests/fixtures`` before committing. The scrubber replaces
every free-text string it finds, but only a person can tell whether a number
or a field name it kept says something about the account.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from _drift import exporter_calls
from _scrub import Scrubber
from beli import Beli, BeliError
from beli._auth import default_session_path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


def fixture_name(name: str, category: str | None) -> str:
    return f"{name}.{category}" if category else name


def record(beli: Beli, categories: list[str] | None, max_items: int) -> dict[str, dict[str, Any]]:
    """Scrubbed fixtures by file stem. Raises ``RuntimeError`` rather than return anything unsafe."""
    scrubber = Scrubber(max_items)
    scrubber.scrub(beli.user_id, "id")  # so the account is always the first fake UUID
    fixtures: dict[str, dict[str, Any]] = {}
    for capture in exporter_calls(beli, categories):
        if capture.error:
            raise RuntimeError(f"{capture.label}: {capture.error}")
        if capture.name == "api-hosts":
            continue  # infrastructure, not account data; the unit tests mock it by hand
        category = (capture.request.params or {}).get("category")
        response = scrubber.scrub(capture.raw)
        problems = scrubber.leaks(response)
        if problems:
            raise RuntimeError(f"{capture.label}: scrubbed response {'; '.join(problems)}")
        entry = {"endpoint": capture.label, "category": category, "response": response}
        fixtures[fixture_name(capture.name, category)] = entry
    return fixtures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--session", default=str(default_session_path()), help="session file")
    parser.add_argument("--interval", type=float, default=2.0, help="seconds between requests")
    parser.add_argument("--categories", help="comma-separated codes (default: the account's)")
    parser.add_argument("--max-items", type=int, default=3, help="keep this many items per list")
    parser.add_argument("--dir", type=Path, default=FIXTURES, help="where the fixtures live")
    args = parser.parse_args(argv)
    categories = (
        [c.strip().upper() for c in args.categories.split(",")] if args.categories else None
    )

    try:
        with Beli.from_session(args.session, min_interval=args.interval) as beli:
            fixtures = record(beli, categories, args.max_items)
    except BeliError as exc:
        print(f"Could not read the API: {type(exc).__name__}. Nothing written.")
        return 1
    except RuntimeError as exc:
        print(f"{exc}. Nothing written.")
        return 1

    args.dir.mkdir(parents=True, exist_ok=True)
    for name, entry in sorted(fixtures.items()):
        (args.dir / f"{name}.json").write_text(json.dumps(entry, indent=2) + "\n")
        print(f"wrote {name}.json")
    for stale in sorted(args.dir.glob("*.json")):
        if stale.stem not in fixtures:
            stale.unlink()
            print(f"removed {stale.name}")
    print("Read `git diff tests/fixtures` before committing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
