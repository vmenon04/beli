"""``beli`` command-line interface."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any

from ._auth import Tokens, default_session_path, save_tokens
from ._version import __version__
from .client import Beli
from .errors import AuthenticationError, BeliError
from .export import FORMATS


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _client(args: argparse.Namespace) -> Beli:
    return Beli.from_session(args.session, min_interval=args.interval)


def cmd_login(args: argparse.Namespace) -> int:
    path = Path(args.session)
    if args.token:
        save_tokens(path, Tokens(refresh=args.token))
        beli = Beli(session_file=path, min_interval=args.interval)
    else:
        email = args.email or os.environ.get("BELI_EMAIL")
        phone = args.phone or os.environ.get("BELI_PHONE")
        if not (email or phone):
            email = input("Beli email: ").strip()
        password = os.environ.get("BELI_PASSWORD") or getpass.getpass("Beli password: ")
        beli = Beli(
            email=email,
            phone=phone,
            password=password,
            session_file=path,
            min_interval=args.interval,
        )
        beli.login()
    with beli:
        user = beli.me()
    print(f"Logged in as @{user.username} ({user.full_name}). Session saved to {path}")
    print("The password was not stored. The session lasts about a week between uses.")
    return 0


def cmd_logout(args: argparse.Namespace) -> int:
    path = Path(args.session)
    if path.exists():
        path.unlink()
        print(f"Removed {path}")
    else:
        print("Not logged in")
    return 0


def cmd_whoami(args: argparse.Namespace) -> int:
    with _client(args) as beli:
        user = beli.me()
        count = beli.rankings.count()
    print(f"@{user.username}  {user.full_name}  {count} places ranked  id={user.id}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    fmt = args.format
    out = (
        Path(args.output)
        if args.output
        else Path(f"beli-export.{ {'sqlite': 'db'}.get(fmt, fmt) }")
    )
    categories = (
        [c.strip().upper() for c in args.categories.split(",")] if args.categories else None
    )
    with _client(args) as beli:
        export = beli.export(categories, on_progress=lambda s: _err(f"  fetching {s}..."))
    files = export.write(out, fmt)
    rated, want = len(export.rated_places()), len(export.bookmarks)
    noted = sum(1 for r in export.rated_places() if r["note"])
    print(
        f"Exported {rated} ranked places ({noted} with notes), {want} want-to-try, "
        f"{len(export.guides)} guides, {len(export.photos)} photos"
    )
    for f in files:
        print(f"  {f}")
    for w in export.warnings:
        _err(f"warning: {w}")
    return 0


def cmd_rankings(args: argparse.Namespace) -> int:
    with _client(args) as beli:
        rankings = beli.rankings.list(args.category.upper(), sort="score")
    if args.limit:
        rankings = rankings[: args.limit]
    if args.json:
        print(json.dumps([r.model_dump(mode="json") for r in rankings], indent=2))
        return 0
    for i, r in enumerate(rankings, 1):
        b = r.business
        where = ", ".join(x for x in (b.neighborhood, b.city) if x)
        score = f"{r.score:4.1f}" if r.score is not None else "   -"
        print(f"{i:4}. {score}  {b.name}  ({where})")
    return 0


def _parse_params(pairs: list[str]) -> dict[str, Any]:
    params = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise SystemExit(f"Bad param {pair!r}; use key=value")
        params[key] = value
    return params


def cmd_get(args: argparse.Namespace) -> int:
    with _client(args) as beli:
        data = beli.get(args.path, params=_parse_params(args.param))
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="beli", description="Unofficial client for the Beli restaurant app."
    )
    parser.add_argument("--version", action="version", version=f"beli {__version__}")
    parser.add_argument(
        "--session", default=str(default_session_path()), help="session file (default: %(default)s)"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="minimum seconds between requests (default: %(default)s)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("login", help="log in and save a session (the password is not stored)")
    who = p.add_mutually_exclusive_group()
    who.add_argument("--email")
    who.add_argument("--phone")
    who.add_argument(
        "--token", metavar="REFRESH_TOKEN", help="use a refresh token instead of a password"
    )
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("logout", help="delete the saved session")
    p.set_defaults(func=cmd_logout)

    p = sub.add_parser("whoami", help="show the logged-in account")
    p.set_defaults(func=cmd_whoami)

    p = sub.add_parser("export", help="export rankings, notes, photos, bookmarks and guides")
    p.add_argument("-f", "--format", choices=FORMATS, default="json")
    p.add_argument("-o", "--output", help="output path (default: beli-export.<ext>)")
    p.add_argument("-c", "--categories", help="comma-separated codes, e.g. RES,BAR (default: all)")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("rankings", help="print your ranked list, best first")
    p.add_argument("-c", "--category", default="RES")
    p.add_argument("-n", "--limit", type=int)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_rankings)

    p = sub.add_parser("get", help="GET any API path; {me} is your user id")
    p.add_argument("path", help="e.g. /api/score-average/{me}/ALL/")
    p.add_argument("-p", "--param", action="append", default=[], metavar="KEY=VALUE")
    p.set_defaults(func=cmd_get)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except AuthenticationError as exc:
        _err(f"beli: {exc}")
        return 2
    except BeliError as exc:
        _err(f"beli: {exc}")
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
