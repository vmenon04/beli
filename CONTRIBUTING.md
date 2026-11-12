# Contributing to beli

Bug reports and pull requests are encouraged and welcome. Because Beli's API is private and is subject to change without notice, the most useful contributions are fixes for endpoints that have changed.

## Setup

You need Python 3.10 or newer and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/vmenon04/beli && cd beli
uv sync --group dev
```

## Checks

Run these before opening a pull request. CI runs the same ones.

```bash
uv run ruff check .
uv run ruff format --check .     # `uv run ruff format .` to fix
uv run mypy
uv run pytest
```

The unit tests use mocked responses and never touch the network.

## Ground rules

- **The package is read-only.** The only requests that are not GETs are login and token refresh. Pull requests that add a write endpoint, or weaken the guard in `Transport._exchange` or its test (`test_read_only`), will not be merged.
- **No account data in the repository.** Test responses are written by hand with made-up values.
- **No tokens, passwords or response bodies in logs, test output or issues.** The message of an `APIError` quotes the response, so report the error type, status code and endpoint instead.
- **One concern per commit**, with a message that says what changed and why.

## Project layout

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
tests/
  conftest.py     mock responses and the `api` fixture
  test_live.py    the only tests that touch the network
```

A call such as `beli.rankings.list()` builds a `Request` with a function from `_endpoints.py` and passes it to `Transport.send`, which adds auth, waits its turn, retries, and runs the request's parser on the answer.

## Adding or changing an endpoint

1. Write or edit the builder in `_endpoints.py`, and a model in `models.py` if the response needs one.
2. Add the method to `_resources.py` (or `_client.py`).
3. Add the matching wrapper to `_async.py`. `tests/test_parity.py` fails until it exists with the same signature.
4. Add a mock response to `tests/conftest.py` and a test.

## Test against the live API

This is read-only. It is safe to run on your account.

```bash
uv run beli login
uv run pytest -m live -v
```

CI cannot run these on a pull request, so please indicate in the pull request that you've you ran them.

## When Beli changes its API

A call raises an error, or the live tests fail.

| Error | Fix |
|---|---|
| `HTTP 4xx from GET /api/...` | The endpoint may have moved or wants different parameters. Please fix it in `src/beli/_endpoints.py`. |
| `<Model> does not validate: <field>` | A field may have changed. Please fix the model in `src/beli/models.py`. |
| `HTTP 429` or `HTTP 5xx` | Rate limiting or an outage. Try again later. |

I recommend to then updating the fake response in `tests/conftest.py`, run the live tests, and release a patch version.

## Reporting a bug

Open an issue with the version (`pip show beli-client`), the call you made, and the error type and endpoint. Ensure that you leave out tokens and the response body.
