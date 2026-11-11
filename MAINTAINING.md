# Maintaining beli

## Test against the live API

Read-only, and safe to run on your own account.

```bash
uv run beli login
uv run pytest -m live -v
```

## When Beli changes its API

A call raises an error, or the live tests fail.

| Error | Fix |
|---|---|
| `HTTP 4xx from GET /api/...` | The endpoint moved or wants different parameters. Fix it in `src/beli/_endpoints.py`. |
| `<Model> does not validate: <field>` | A field changed. Fix the model in `src/beli/models.py`. |
| `HTTP 429` or `HTTP 5xx` | Rate limiting or an outage. Try again later. |

Then update the fake response in `tests/conftest.py`, run the live tests, and release a patch version.

## Release

1. Run the checks and the live tests.
2. Set the version in `src/beli/_version.py` and finish its entry in `CHANGELOG.md`.
3. Merge to `main`, then tag it:

   ```bash
   git tag v0.2.0 && git push origin v0.2.0
   ```

4. Approve the `pypi` environment when `release.yml` asks. It publishes to PyPI.

## Daily check (optional)

`live.yml` runs the live tests every day and opens an `api-drift` issue when they fail. It does nothing until you set it up:

1. Create a throwaway Beli account with an email and password, and rank a few places on it. Do not use your own account: its password goes in a GitHub secret.
2. Record what its responses look like (field names and types only) and commit the result:

   ```bash
   export BELI_SESSION_FILE=~/.config/beli/ci-session.json
   uv run beli login --email <the account's email>
   uv run python scripts/snapshot_shapes.py
   unset BELI_SESSION_FILE
   ```

3. Add the repository secrets `BELI_CI_EMAIL` and `BELI_CI_PASSWORD`.
