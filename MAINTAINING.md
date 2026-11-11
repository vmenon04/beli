# Maintaining beli

## What runs automatically

| Workflow | When | What it does |
|---|---|---|
| `ci.yml` | every push and pull request | ruff, mypy, pytest on Python 3.10 to 3.13. No network. |
| `live.yml` | daily at 10:23 UTC, or by hand | Logs in with the CI account, runs `pytest -m live` and `snapshot_shapes.py --check`. On failure it opens or updates one issue labeled `api-drift`. |
| `release.yml` | on a `v*` tag | Builds and publishes to PyPI. |

`live.yml` skips itself until the two Beli secrets exist, so it is optional. Without it, run `uv run pytest -m live` yourself before each release.

## Checking against the live API by hand

Everything here only reads. Your own account is fine for this.

```bash
uv sync --group dev
uv run beli login
uv run pytest -m live -v
```

Requests are spaced two seconds apart; set `BELI_LIVE_INTERVAL` to change that.

## Setting up the daily check

### 1. A CI account

`live.yml` logs in with an email and a password stored as GitHub secrets, so use a throwaway Beli account, not yours.

1. Sign up in the Beli app with an email address and a password. "Sign in with Apple" or Google accounts have no password to log in with.
2. Give it a little of everything the exporter reads, so the recorded shapes are not empty lists: three ranked restaurants, a note, a photo, a visit date, one place on Want to Try, and one guide with a place in it.
3. Then leave it alone. Shapes are compared exactly, so new kinds of data on the account show up as drift. If you do change it, record the shapes again.

### 2. Record the shapes

A shape is the set of field names and JSON types in a response, never the values. Record them with the CI account, because that is the account CI compares against.

```bash
export BELI_SESSION_FILE=~/.config/beli/ci-session.json   # keeps it apart from your own session
uv run beli login --email <the CI account's email>
uv run python scripts/snapshot_shapes.py                  # writes tests/shapes/
unset BELI_SESSION_FILE
```

Skim `tests/shapes/` and commit it.

### 3. Secrets

Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `BELI_CI_EMAIL` | The CI account's email. |
| `BELI_CI_PASSWORD` | The CI account's password. |

Then run it once by hand: Actions → Live API check → Run workflow.

### 4. Repository settings

- **Settings → Environments → pypi:** add yourself as a required reviewer, so a tag cannot publish without your approval.
- **Settings → Rules → Rulesets:** protect `main` and restrict who can create `v*` tags to yourself.

PyPI needs no secret: `release.yml` uses trusted publishing through the `pypi` environment.

## When an `api-drift` issue shows up

The issue says which of login, live tests and shapes failed. It is updated in place each day while the check keeps failing. Close it when the check passes again.

| The issue shows | Meaning | What to do |
|---|---|---|
| Only "Login" | The CI account, not the API. | Log in to the account in the app, check the two secrets, rerun the workflow. |
| Only `HTTP 429` or `HTTP 5xx` | Rate limiting or an outage. | Rerun later. |
| `HTTP 4xx from GET /api/...` | The endpoint moved or wants different parameters. | Fix its builder in `src/beli/_endpoints.py`. |
| `<Model> does not validate: <field> (<error>)` | A response no longer fits its model. | Fix the model in `src/beli/models.py`: make the field optional if it is `missing`, widen its type if it is a type error. |
| A shape diff | Fields were added, removed or changed type. `-` lines are what `tests/shapes/` holds, `+` lines are what the API sent. | A new field needs no code change: models keep unknown fields. For a removed field or a changed type, fix the model and anything in `export.py` that reads it. |

After a fix: add or adjust a unit test and the fake response in `tests/conftest.py`, run `uv run pytest -m live -v`, record the shapes again with the CI account, and release a patch version.

## Cutting a release

1. `main` is green, and the live tests pass (the latest "Live API check" run, or `uv run pytest -m live` by hand).
2. Set the new version in `src/beli/_version.py`. While the version is 0.x, anything that changes behaviour for existing users is a minor bump.
3. In `CHANGELOG.md`, check the entry for this version covers everything users will notice and remove "(unreleased)" from its heading.
4. `uv run ruff check . && uv run mypy && uv run pytest`, then `uv build` and look at the contents of `dist/`.
5. Commit (`Release 0.2.0`), open a pull request, merge.
6. Tag the merge commit and push the tag:

   ```bash
   git switch main && git pull
   git tag v0.2.0
   git push origin v0.2.0
   ```

7. Approve the `pypi` environment when `release.yml` asks.
8. Check `pip install beli==0.2.0` in a clean environment, then paste the changelog entry into the GitHub release notes.
