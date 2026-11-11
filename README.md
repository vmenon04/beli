# beli

[![CI](https://github.com/vmenon04/beli/actions/workflows/ci.yml/badge.svg)](https://github.com/vmenon04/beli/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/beli)](https://pypi.org/project/beli/)
[![Python](https://img.shields.io/pypi/pyversions/beli)](https://pypi.org/project/beli/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Unofficial, read-only Python client and exporter for [Beli](https://beliapp.com), the restaurant ranking app.

Beli has no public API and no export button. This package reads your rankings, scores, notes, visit dates, photos, Want to Try list and guides through the private API the app uses, and writes them to JSON, CSV or SQLite.

> Not affiliated with or endorsed by Beli. The API is reverse engineered and can change without notice. Use it on your own account.

## Install

```bash
pip install beli
```

Requires Python 3.10 or newer.

## Export your data

```bash
beli login                # asks for your email and password
beli export -f sqlite     # writes beli-export.db
```

`-f` can be `json`, `csv` or `sqlite`. Each ranked place comes with its rank, score, name, city, cuisines, price, your note, visit dates, photo URLs and the guides it is in.

```bash
sqlite3 beli-export.db "SELECT rank, score, name, note FROM rated LIMIT 10"
```

Other commands:

```bash
beli whoami
beli rankings -c RES -n 20                # your top 20 restaurants
beli export -c RES,BAR -f csv -o ~/beli.csv
beli get /api/score-average/{me}/ALL/     # any GET endpoint; {me} is your user id
beli logout
```

## Use it from Python

```python
from beli import Beli

with Beli.from_session() as beli:  # the session saved by `beli login`
    for r in beli.rankings.list("RES", sort="score")[:10]:
        print(f"{r.score:.1f}  {r.business.name}")

    export = beli.export()
    export.write("beli.json")
```

Without a saved session, pass credentials, or set `BELI_EMAIL` and `BELI_PASSWORD` and call `Beli()`:

```python
beli = Beli(email="you@example.com", password="...")
```

`AsyncBeli` has the same methods for `asyncio` code:

```python
from beli import AsyncBeli

async with AsyncBeli.from_session() as beli:
    rankings = await beli.rankings.list("RES")
```

### API

| | Methods |
|---|---|
| `beli` | `me()`, `categories()`, `export()`, `get(path)` |
| `beli.rankings` | `list(category, sort=None)`, `all()`, `visit_dates(business_id)`, `count()`, `count_this_year()` |
| `beli.notes` | `list()`, `get(business_id)` |
| `beli.scores` | `list()`, `averages()` |
| `beli.photos` | `list()` |
| `beli.bookmarks` | `list(category)` |
| `beli.guides` | `list()`, `items()`, `get(guide_id)` |
| `beli.users` | `get(user_id)`, `followers()`, `following()`, `streak()` |
| `beli.places` | `search(term, city=...)`, `hours(business_id)`, `trending(category)` |

- Most methods take `user=` to read another user's data, if their profile is visible to you.
- `beli.get(path)` sends a GET to any other endpoint and returns the JSON.
- Results are pydantic models (`beli.models`). Fields the package does not know about are kept in `model_extra`.
- Rankings come back best first, as the API sends them. `sort="score"` sorts them by score on your side.

### Errors

Every exception is a `BeliError`.

| Error | Meaning |
|---|---|
| `AuthenticationError` | Login failed, or there are no usable credentials. |
| `APIError` | The API answered with an error status (`.status_code`, `.body`). Subclasses: `BadRequestError`, `PermissionDeniedError`, `NotFoundError`, `RateLimitError`, `ServerError`. |
| `UnexpectedResponseError` | The API answered in a form this version cannot read. Beli has probably changed something: upgrade, and open an issue if that does not help. |

## Authentication

`beli login` sends your email (or phone) and password to Beli and saves the tokens it gets back to `~/.config/beli/session.json`, readable only by you. The password is never stored. A session lasts about a week between uses and is refreshed automatically.

A client uses the first of these that it finds, and never mixes them:

1. arguments: `email` or `phone` with `password`, or `refresh_token`;
2. the session file (`Beli.from_session()` or `session_file=`);
3. environment variables: `BELI_EMAIL` or `BELI_PHONE` with `BELI_PASSWORD`, or `BELI_REFRESH_TOKEN`.

If you sign in to Beli with Apple or Google, your account has no password. Capture a refresh token from the app's traffic (for example with mitmproxy) and run `beli login --token <refresh token>`.

## Good to know

- **Read-only.** Nothing here changes your account. The only requests that are not GETs are login and token refresh, and the client refuses to send anything else.
- **Rate limits.** Requests are spaced one second apart (`min_interval=`, or `--interval` on the command line), and rate-limit and server errors are retried with backoff. A full export is about a dozen requests.
- **Threads.** One `Beli` can be shared between threads.
- **Stability.** The public API is what you can import from `beli`, the models in `beli.models`, and the `beli` command. Names starting with an underscore are internal. Until 1.0, minor releases (0.2 to 0.3) can change behaviour, so pin `beli>=0.2,<0.3`. See the [changelog](CHANGELOG.md).
- **When Beli changes its API,** a call raises `UnexpectedResponseError` or an `APIError`. Please [open an issue](https://github.com/vmenon04/beli/issues) with the endpoint and the error type. Leave out the message body: it can quote your data.

## Development

```bash
git clone https://github.com/vmenon04/beli && cd beli
uv sync --group dev
uv run ruff check . && uv run mypy && uv run pytest
```

The unit tests use mocked responses and never touch the network. To run the read-only tests against your own account:

```bash
uv run beli login
uv run pytest -m live
```

The code layout and the project's rules are in [CLAUDE.md](CLAUDE.md). Releases and the daily check that watches for API changes are in [MAINTAINING.md](MAINTAINING.md).

## Credits

The endpoints were documented by [horse-3903/beli-api-spec](https://github.com/horse-3903/beli-api-spec) and [ProjectBarks/beli-api](https://github.com/ProjectBarks/beli-api), both MIT licensed.

## License

[MIT](LICENSE)
