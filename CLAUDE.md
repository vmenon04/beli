# beli

Unofficial, read-only Python client and exporter for the Beli restaurant app. The API is private and reverse engineered, so most of the work here is noticing when it changes and adapting.

## Hard rules

1. **Read-only.** The only requests that are not GETs are login (`POST /api/token/`) and token refresh (`POST /api/token/refresh/`). Never add a write endpoint. Never weaken the guard (`Call.__post_init__` and `Session.send` in `src/beli/_session.py`) or its test (`test_read_only` in `tests/test_client.py`).
2. **Never run anything against the live Beli API.** That means `pytest -m live`, `scripts/snapshot_shapes.py`, the `beli` CLI, and any ad hoc request to a Beli host. Only the maintainer runs these, or CI with its secrets.
3. **No AI attribution.** No `Co-Authored-By` trailers, no "generated with" footers, no session links, no mention of assistants or tools in commit messages, PR text, comments or files.
4. **Small commits, one concern each.** Run ruff, mypy and pytest before each one (see "Checks"). The message says what changed and why.
5. **Never commit account data.** Test responses are written by hand with fake values: `https://example.com/...` URLs, UUIDs starting `00000000-0000-4000-8000-`, made-up names. `tests/shapes/` holds field names and JSON types only.
6. **Never print or log tokens, passwords or response bodies.** `str()` of an `APIError` or a pydantic `ValidationError` contains response data. In scripts, tests that run in CI, and issue or PR text, use `_drift.describe()` instead.

Do not merge, tag, publish, or change `src/beli/_version.py` unless the maintainer asks.

## Layout

```
src/beli/
  _constants.py        hosts, required headers, flags observed in the app's traffic
  _auth.py             JWT decoding, session file load/save
  _session.py          the sans-I/O core: Request, Config, credential precedence,
                       host discovery, login/refresh/retry as generator flows,
                       the read-only guard
  _transport.py        SyncTransport and AsyncTransport: the only code that does I/O
  _endpoints.py        one pure builder per endpoint -> Request (path, params, parser)
  _plans.py            multi-request operations (export, all rankings) as generators
  _resources.py        sync public methods     } mirrored pairs, each method one line;
  _async_resources.py  async public methods    } tests/test_parity.py fails if a pair
  _client.py           Beli                    } differs in anything but await
  _async_client.py     AsyncBeli               }
  client.py            re-exports Beli and AsyncBeli
  models.py            pydantic models; unknown fields are kept in model_extra
  export.py            Export and the JSON / CSV / SQLite writers
  cli.py               the `beli` command
scripts/
  _drift.py            response shapes, safe error descriptions, export capture
  snapshot_shapes.py   live: record or --check tests/shapes/
tests/
  conftest.py          hand-written mock responses and the `api` respx fixture
  shapes/              recorded response shapes, one file per endpoint
  test_live.py         the only tests that touch the network (marker: live)
.github/workflows/     ci, release, live (daily)
```

How a call flows: a resource method builds a `Request` with a builder from `_endpoints.py` and passes it to the transport. `Session.send` turns it into effects (`Call`, `Sleep`, `Exclusive`), and the transport carries those out. To add or change an endpoint you touch the builder, perhaps a model, and the one-line method in **both** `_resources.py` and `_async_resources.py`.

Builders that need a user take `user_id` as their first argument. There is no "current user" placeholder: resources pass `self._uid(user)`.

## Checks

```bash
uv sync --group dev
uv run ruff check .
uv run ruff format --check .     # `uv run ruff format .` to fix
uv run mypy
uv run pytest                    # live tests are deselected by default
```

All four must pass before every commit. The suite includes the sync/async parity check, and the read-only guard test.

## When the API changes

See "When an `api-drift` issue shows up" in `MAINTAINING.md`. Keep every request a GET: if a fix seems to need a write, stop and say so.
