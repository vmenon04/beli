# beli

Unofficial, read-only Python client and exporter for the Beli restaurant app. The API is private and reverse engineered, so it can change without notice.

## Hard rules

1. **Read-only.** The only requests that are not GETs are login (`POST /api/token/`) and token refresh (`POST /api/token/refresh/`). Never add a write endpoint. Never weaken the guard (`Transport._exchange` in `src/beli/_transport.py`) or its test (`test_read_only` in `tests/test_client.py`).
2. **Never run anything against the live Beli API.** That means `pytest -m live`, `scripts/snapshot_shapes.py`, the `beli` CLI, and any ad hoc request to a Beli host. Only the maintainer runs these, or CI with its secrets.
3. **No AI attribution.** No `Co-Authored-By` trailers, no "generated with" footers, no session links, no mention of assistants or tools in commit messages, PR text, comments or files.
4. **Small commits, one concern each.** Run the checks below before each one. The message says what changed and why.
5. **Never commit account data.** Test responses are written by hand with fake values: `https://example.com/...` URLs, made-up names. `tests/shapes/` holds field names and JSON types only.
6. **Never print or log tokens, passwords or response bodies.** `str()` of an `APIError` contains response data. In scripts, tests that run in CI, and issue or PR text, use `describe()` from `scripts/snapshot_shapes.py` instead.

Do not merge, tag, publish, or change `src/beli/_version.py` unless the maintainer asks.

## Layout

```
src/beli/
  _constants.py   hosts, required headers, flags observed in the app's traffic
  _auth.py        tokens, the session file, which credentials win
  _transport.py   Request and Transport: login, refresh, pacing, retries,
                  host discovery, the read-only guard. The only code that does I/O.
  _endpoints.py   one function per endpoint -> Request (path, params, parser)
  _resources.py   beli.rankings, beli.notes, ...: one short method per endpoint
  _client.py      Beli, including export()
  _async.py       AsyncBeli: runs Beli on a background thread, one wrapper per method
  models.py       pydantic models; unknown fields are kept in model_extra
  export.py       Export and the JSON / CSV / SQLite writers
  errors.py       every exception the package raises
  cli.py          the `beli` command
scripts/
  snapshot_shapes.py   live: record or --check tests/shapes/
tests/
  conftest.py     hand-written mock responses and the `api` respx fixture
  shapes/         recorded response shapes, one file per endpoint
  test_live.py    the only tests that touch the network (marker: live)
.github/workflows/     ci, release, live (daily)
```

How a call flows: `beli.rankings.list()` in `_resources.py` builds a `Request` with `ep.rankings(...)` from `_endpoints.py` and passes it to `Transport.send`, which adds auth, waits its turn, retries, and runs the request's parser on the answer.

To add or change an endpoint:

1. the builder in `_endpoints.py`, and a model in `models.py` if the response needs one;
2. the method in `_resources.py` (or `_client.py`);
3. the matching wrapper in `_async.py`. `tests/test_parity.py` fails until it exists and has the same signature;
4. a fake response in `tests/conftest.py` and a test.

## Checks

```bash
uv sync --group dev
uv run ruff check .
uv run ruff format --check .     # `uv run ruff format .` to fix
uv run mypy
uv run pytest                    # live tests are deselected by default
```

All four must pass before every commit.

## When the API changes

See "When Beli changes its API" in `MAINTAINING.md`. Keep every request a GET: if a fix seems to need a write, stop and say so.
