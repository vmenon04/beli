# beli

Unofficial Python client and exporter for [Beli](https://beliapp.com), the restaurant ranking app.

Beli has no public API and no export button. This package talks to the private API the app uses, so you can read your own rankings, scores, notes, visit dates, photos, Want to Try list and guides into JSON, CSV or SQLite, or script against them in Python.

[![CI](https://github.com/vmenon04/beli/actions/workflows/ci.yml/badge.svg)](https://github.com/vmenon04/beli/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/beli)](https://pypi.org/project/beli/)
[![Python](https://img.shields.io/pypi/pyversions/beli)](https://pypi.org/project/beli/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

> Not affiliated with or endorsed by Beli. The API is reverse engineered and can change without notice. Use it on your own account, at a polite request rate.

## Install

```bash
pip install beli        # or: uv tool install beli / pipx install beli
```

Python 3.10+. The only dependencies are `httpx` and `pydantic`.

## Export your data in two commands

```bash
beli login                         # prompts for email and password
beli export -f sqlite              # writes beli-export.db
```

| Format | Output |
|---|---|
| `json` | One file: flattened `rated` and `want_to_try` rows, guides, score averages, plus every raw API object under `raw` so nothing is lost |
| `csv` | `beli-export.csv` (ranked places) and `beli-export-want-to-try.csv`. Opens in Sheets or Excel |
| `sqlite` | Tables for places, rankings, visits, notes, photos, want_to_try, guides, plus a `rated` view |

```bash
sqlite3 beli-export.db "SELECT rank, score, name, note FROM rated WHERE category = 'RES' LIMIT 10"
```

Each ranked place row has: rank, category, score, name, neighborhood, city, country, cuisines, price, lat/lng, your note, visit dates, when you ranked it, photo URLs, which of your guides it's in, website, Google place id and Beli link.

Other commands:

```bash
beli whoami                        # username, name and ranked count
beli rankings -c RES -n 20         # your top 20 restaurants
beli export -c RES,BAR -f csv -o ~/beli.csv
beli get /api/score-average/{me}/ALL/   # GET any endpoint; {me} is your user id
beli logout
```

## Use it as a library

```python
from beli import Beli

with Beli.from_session() as beli:  # reuses `beli login`
    for r in beli.rankings.list("RES", sort="score")[:10]:
        note = beli.notes.get(r.business.id)
        print(f"{r.score:.1f}  {r.business.name}  {note or ''}")
```

Or pass credentials directly:

```python
beli = Beli(email="you@example.com", password="...")
```

`Beli()` with no arguments reads `BELI_EMAIL` and `BELI_PASSWORD` from the environment. See [Authentication](#authentication) for the order.

Async works the same way:

```python
from beli import AsyncBeli

async with AsyncBeli.from_session() as beli:
    export = await beli.export()
    export.write("beli.json")
```

### Errors

Everything the package raises is a `BeliError`:

| Error | When |
|---|---|
| `AuthenticationError` | Login failed, or there are no usable credentials. |
| `APIError` and its subclasses (`BadRequestError`, `PermissionDeniedError`, `NotFoundError`, `RateLimitError`, `ServerError`) | The API answered with an error status. `status_code` and `body` are on the exception. |
| `UnexpectedResponseError` | The API answered, but not in a form this version can read. Beli has probably changed something: upgrade, and if that does not help, open an issue. `problem` names the fields that did not fit and never quotes the response. |

### What's covered

| Resource | Methods |
|---|---|
| `beli.rankings` | `list(category, sort=None)`, `all(sort=None)`, `visit_dates(business_id)`, `count()`, `count_this_year()` |
| `beli.notes` | `list()`, `get(business_id)` |
| `beli.scores` | `list()`, `averages()` (by city, country, cuisine) |
| `beli.photos` | `list()` |
| `beli.bookmarks` | `list(category)` |
| `beli.guides` | `list()`, `items()`, `get(guide_id)` |
| `beli.users` | `get(user_id)`, `followers()`, `following()`, `streak()` |
| `beli.places` | `search(term, city=...)`, `hours(business_id)`, `trending(category)` |
| `beli` | `me()`, `categories()`, `export()`, `get(path)` |

Methods that read a user's data take `user=` to read someone else's (if their profile is visible to you). Anything else in the [433-operation spec](https://github.com/horse-3903/beli-api-spec) is one `beli.get(...)` away, as long as it's a GET.

`rankings.list()` returns places in the order the API sends them. Pass `sort="score"` for highest score first; places with the same score keep the API's order.

Responses are pydantic models. Beli adds fields often, so unknown fields are kept in `model.model_extra` instead of being dropped.

**Read-only.** Nothing in this package changes your account. The only requests that aren't GETs are login and token refresh, and the transport refuses to send anything else.

## Authentication

Login is `email` (or `phone`) plus password, sent to Beli's token endpoint. You get an access token (about 20 minutes) and a refresh token (about 7 days). The client refreshes automatically and retries once on a 401.

- `beli login` saves only the tokens, to `~/.config/beli/session.json` with `0600` permissions. Your password is never written to disk. Override the path with `BELI_SESSION_FILE`.
- If your account has no password (for example, you sign in with Apple or Google), capture a refresh token from the app's traffic (for example with mitmproxy) and run `beli login --token <refresh>`, or set `BELI_REFRESH_TOKEN`.

A client takes its credentials from the first of these that has any, and never mixes them:

1. Constructor arguments: `email` or `phone` with `password`, `refresh_token`, `access_token`.
2. The session file (`session_file=`, or `Beli.from_session()`), if it holds a token that has not expired.
3. The environment: `BELI_REFRESH_TOKEN`, or `BELI_PASSWORD` with `BELI_EMAIL` or `BELI_PHONE`.

New tokens are saved to the session file whichever source they came from. To see which source was used, turn on debug logging for the `beli` logger:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
```

Before its first request to the main API, a client asks Beli which hosts to use (`/api/api-hosts/`) and keeps the answer for its lifetime. If that fails it uses the built-in hosts. Pass `discover_hosts=False` to skip the question.

One `Beli` can be shared between threads: token refresh is done once, under a lock.

## Rate limits

Beli answers bursts with HTTP 429. The client spaces requests at least 1 second apart (`min_interval=`, or `--interval` on the CLI), honors `Retry-After`, and retries 429/502/503/504 with backoff. A full export is about a dozen requests.

## Reliability

Every endpoint used here comes from [beli-api-spec](https://github.com/horse-3903/beli-api-spec) and [ProjectBarks/beli-api](https://github.com/ProjectBarks/beli-api), which documented the API from captured traffic and the app's code. The read endpoints the exporter relies on were verified there against a live account.

A private API changes without warning, so the repository watches for it:

- The unit tests run against mocked responses and never touch the network.
- A daily workflow logs in with a throwaway account, runs the live tests, and compares the shape of every response the exporter reads (field names and JSON types, no values) with the shapes stored in `tests/shapes/`. A difference opens an `api-drift` issue with the diff.

To check against your own account:

```bash
beli login
pytest -m live        # read-only
```

If Beli changes something before the daily check catches it, please open an issue with the endpoint and the error.

## What you can rely on

The public API is:

- everything importable from `beli` itself: `Beli`, `AsyncBeli`, `Export`, `Tokens`, `CATEGORY_NAMES` and the errors;
- the models in `beli.models`;
- the `beli` command and its options.

Modules and names that start with an underscore (`beli._transport`, `beli._endpoints`, ...) are internal and can change in any release.

While the version is 0.x, a minor release (0.2 to 0.3) can change behaviour and a patch release (0.2.0 to 0.2.1) does not. Pin `beli>=0.2,<0.3` if you depend on it. Every change users will notice is in [CHANGELOG.md](CHANGELOG.md).

One thing no version number can promise: Beli can change its API at any time. Fields on the models can become optional or disappear when it does, and a release that follows such a change may be a patch release. Fields this package does not know about are kept on each model in `model_extra`.

## Development

```bash
git clone https://github.com/vmenon04/beli && cd beli
uv sync --group dev
uv run pytest
uv run ruff check . && uv run mypy
```

The layout and rules are in [CLAUDE.md](CLAUDE.md). The daily check, what to do when the API changes, and releases are in [MAINTAINING.md](MAINTAINING.md).

There is one implementation of the client. `AsyncBeli` runs it on a background thread, and `tests/test_parity.py` fails if it is missing a method.

## Credits

API research by [horse-3903/beli-api-spec](https://github.com/horse-3903/beli-api-spec) and [ProjectBarks/beli-api](https://github.com/ProjectBarks/beli-api), both MIT licensed.

## License

MIT
