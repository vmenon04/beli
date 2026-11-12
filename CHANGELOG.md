# Changelog

Until 1.0, a minor release (0.2 to 0.3) may include breaking changes, and a patch release (0.2.0 to 0.2.1) does not.

## 0.2.0

First public release.

- Export rankings, scores, notes, visit dates, photos, the Want to Try list and guides to JSON, CSV or SQLite.
- `Beli`, a Python client with typed results, and `AsyncBeli` for asyncio code.
- The `beli` command: `login`, `logout`, `whoami`, `rankings`, `export` and `get`.
- Read-only: the client refuses to send anything other than GETs, login and token refresh.
- Requests are spaced one second apart, and rate-limit and server errors are retried with backoff.
- Sessions are saved without the password and refreshed automatically.
- A response the package cannot read raises `UnexpectedResponseError`, which names the endpoint and the fields that changed.
