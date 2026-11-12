# beli

[![CI](https://github.com/vmenon04/beli/actions/workflows/ci.yml/badge.svg)](https://github.com/vmenon04/beli/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/beli-client)](https://pypi.org/project/beli-client/)
[![Python](https://img.shields.io/pypi/pyversions/beli-client)](https://pypi.org/project/beli-client/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Unofficial, read-only Python client and exporter for [Beli](https://beliapp.com), the restaurant ranking app.

Beli has no public API and no export button. This package reads your rankings, scores, notes, visit dates, photos, Want to Try list and guides through the private API the app uses, and writes them to JSON, CSV or SQLite.

> Not affiliated with or endorsed by Beli. The API is reverse engineered and can change without notice. Use it on your own account.

## Install

```bash
pip install beli-client
```

Requires Python 3.10 or newer. The package installs as `beli-client` and imports as `beli`.

## Export your data

```bash
beli login                # asks for your email and password
beli export -f sqlite     # writes beli-export.db
```

The format flag `-f` can be set to `json`, `csv` or `sqlite`.

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

Most methods take `user=` to read another user's data. `beli.get(path)` sends a GET to any other endpoint. The results are pydantic models from `beli.models`.

Every exception is a `BeliError`. If Beli changes its API, you may get an `UnexpectedResponseError`: upgrade, or [open an issue](https://github.com/vmenon04/beli/issues).

## Authentication

`beli login` saves a session token to `~/.config/beli/session.json`. Your password is never stored. The session lasts about a week between uses.

If you sign in to Beli with Apple or Google, you will need to capture a refresh token from the app's traffic and run `beli login --token <refresh token>`.

## Notes

For now, this implementation is read-only. Requests are also spaced one second apart and retried when Beli asks you to slow down. Future releases may include breaking changes, please check the changelog ([CHANGELOG.md](CHANGELOG.md)) before upgrading.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) and [MAINTAINING.md](MAINTAINING.md).

## Credits

The endpoints were documented by [horse-3903/beli-api-spec](https://github.com/horse-3903/beli-api-spec) and [ProjectBarks/beli-api](https://github.com/ProjectBarks/beli-api).

## License

[MIT](LICENSE)
