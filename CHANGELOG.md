# Changelog

Versions follow `0.MINOR.PATCH` while the package is pre-1.0: a minor bump can change behaviour for existing users, a patch bump does not.

## 0.2.0 (unreleased)

### Changed

- `rankings.list()` and `rankings.all()` return rankings in the order the API sends them. They used to be sorted by score. Pass `sort="score"` for best first. `beli rankings` on the command line still shows best first.
- Credentials come from exactly one source, in this order: constructor arguments, then the saved session file (if its token has not expired), then the environment. Sources are never mixed. Two consequences:
  - a saved session now wins over `BELI_REFRESH_TOKEN`;
  - `Beli(email=...)` no longer takes its password from `BELI_PASSWORD`. Pass both, or neither.
- A response the package cannot read raises `UnexpectedResponseError` (a `BeliError`) instead of a pydantic `ValidationError`. The original error is chained as `__cause__`.
- API hosts are discovered from `/api/api-hosts/` before the first request, which costs one extra request per client. The built-in hosts are used if discovery fails. Pass `discover_hosts=False` to skip it.

- `AsyncBeli` now runs the blocking client on one background thread instead of having its own implementation, so the two clients cannot behave differently. Its methods are unchanged. `http_client=` on `AsyncBeli` now takes an `httpx.Client`, not an `httpx.AsyncClient`. Calls made at the same time run one after another, as request pacing already made them.

### Added

- `sort=` on `rankings.list()` and `rankings.all()`.
- `discover_hosts=` on `Beli` and `AsyncBeli`.
- Which credential source was used is logged at debug level on the `beli` logger.

### Fixed

- One `Beli` can be shared between threads: a token is refreshed once, under a lock, instead of once per thread.

## 0.1.0

First release.
