# Maintaining beli

What has to be set up once, what runs by itself afterwards, and what to do when it reports something.

## What runs automatically

| Workflow | When | What it does |
|---|---|---|
| `ci.yml` | every push and PR | ruff, mypy, pytest on Python 3.10 to 3.13. No network. |
| `live.yml` | daily, 10:23 UTC, or by hand | Logs in with the CI account, runs `pytest -m live` and `snapshot_shapes.py --check`. On failure opens or updates the `api-drift` issue. |
| `upstream.yml` | Mondays, 09:41 UTC, or by hand | Runs `check_upstream.py`. On a change opens or updates the `upstream-change` issue. |
| `repair.yml` | when either issue is first opened, when you put one of the two labels on an issue, or by hand | Has an agent propose a fix on `repair/issue-N` and opens a pull request. Never merges. |
| `release.yml` | on a `v*` tag | Builds and publishes to PyPI. |

`live.yml` does nothing until the two Beli secrets exist, and `repair.yml` fails fast without its API key, so nothing below is urgent. Until `tests/shapes/` has been recorded (see "First run"), `live.yml` reports every endpoint as having no stored shape.

## One-time setup

### 1. The CI account

`live.yml` needs a Beli account it can log into with an email and a password. Use a throwaway one, not yours: its password sits in a GitHub secret and its data ends up, scrubbed, in this repository.

1. Sign up in the Beli app with a new email address and a password. Not "Sign in with Apple" or Google: those accounts have no password to log in with.
2. Give it a little of everything the exporter reads, so the recorded shapes are not empty lists:
   - at least three ranked restaurants, two of them close enough to share a score if you can manage it (this is what answers the ordering question in `tests/test_live.py::test_ranking_order`);
   - a note on one of them, a photo on one, a visit date on one;
   - one place on Want to Try;
   - one guide with at least one place in it.
3. Then leave it alone. Shapes are compared exactly, so adding the account's first bookmark in a new category, or deleting its only photo, shows up as drift. If you do change its data, re-record the shapes (below).

### 2. Secrets

Settings → Secrets and variables → Actions → New repository secret.

| Secret | Used by | Value |
|---|---|---|
| `BELI_CI_EMAIL` | `live.yml` | The CI account's email. |
| `BELI_CI_PASSWORD` | `live.yml` | The CI account's password. |
| `ANTHROPIC_API_KEY` | `repair.yml` | An Anthropic API key. Set a spend limit on it. |
| `REPAIR_TOKEN` (optional) | `repair.yml` | A fine-grained personal access token for this repository with Contents and Pull requests set to read and write. See "Repair pull requests and CI". |

PyPI needs no secret: `release.yml` uses trusted publishing through the `pypi` environment.

### 3. Repository settings

- **Settings → Actions → General → Workflow permissions:** tick "Allow GitHub Actions to create and approve pull requests". Without it `repair.yml` can push its branch but not open the pull request (unless `REPAIR_TOKEN` is set).
- **Settings → Environments → pypi:** add yourself as a required reviewer. A tag then cannot publish without your approval, whoever or whatever pushed it.
- **Settings → Rules → Rulesets:** protect `main` (require a pull request) and restrict who can create `v*` tags to yourself.

The labels `api-drift` and `upstream-change` are created by the workflows the first time they are needed.

## First run

Nothing here has been run against the live API yet. Do this once, in this order, with the CI account so that what you record is what CI will compare against.

```bash
uv sync --group dev

# Keep the CI account's session apart from your own.
export BELI_SESSION_FILE=~/.config/beli/ci-session.json
uv run beli login --email <the CI account's email>

uv run pytest -m live -v                         # do the models still parse real responses?
uv run python scripts/snapshot_shapes.py         # writes tests/shapes/
uv run python scripts/record_fixtures.py         # writes tests/fixtures/
```

Then:

1. Read `git diff --stat` and skim `tests/shapes/`: field names and types only.
2. Read every file in `tests/fixtures/`. The scrubber replaces all free text, ids, URLs, coordinates and dates, and refuses to write if it can still find an original value. It keeps scores, counts, prices and field names. Make sure nothing you see identifies the account.
3. `uv run pytest`. Two tests that were skipped now run: they replay the export from the fixtures and scan them for anything recognisable.
4. Commit shapes and fixtures separately.
5. Note what `test_ranking_order` said and update the TODO on `rankings()` in `src/beli/_endpoints.py`: does the API return rankings best first, and how are ties ordered?
6. Run the "Live API check" workflow by hand once (Actions → Live API check → Run workflow) and confirm it passes.

`unset BELI_SESSION_FILE` when you are done, or your own `beli` commands will use the CI account.

## Running things locally

All of these read only. Requests are spaced two seconds apart by default; change it with `--interval` (scripts) or `BELI_LIVE_INTERVAL` (live tests).

| Command | Needs | Does |
|---|---|---|
| `uv run pytest` | nothing | Unit tests, mocked. |
| `uv run pytest -m live -v` | a session (`beli login`) | The live tests. |
| `uv run python scripts/snapshot_shapes.py --check` | a session | Compares live response shapes with `tests/shapes/`. Exit 1 and a diff if they differ. |
| `uv run python scripts/snapshot_shapes.py` | a session | Rewrites `tests/shapes/`. |
| `uv run python scripts/record_fixtures.py` | a session | Rewrites `tests/fixtures/`, scrubbed. |
| `uv run python scripts/check_upstream.py` | internet (GitHub only) | Compares the upstream specs with `tests/upstream/`. |
| `uv run python scripts/check_upstream.py --update` | internet (GitHub only) | Accepts the current upstream specs. |

Which account a command uses follows the client's precedence: the session file (`BELI_SESSION_FILE`, else `~/.config/beli/session.json`) if it holds a live token, otherwise `BELI_EMAIL` / `BELI_PASSWORD` or `BELI_REFRESH_TOKEN` from the environment. Shapes recorded from your own account will not match the CI account's, so always record with the CI account.

## When an issue shows up

### `api-drift`

The body says which of login, live tests and shapes failed. A new issue also starts a repair run, so a pull request usually follows within the hour.

- **Only "Login":** the account, not the API. Log in to the CI account in the app, check the two secrets, rerun the workflow.
- **Only HTTP 429 or 5xx lines:** rate limiting or an outage. Rerun later and close the issue if it passes.
- **Shape diffs or validation errors:** a real change. Review the repair pull request, or fix it yourself following "Repair procedure" in `CLAUDE.md`.

The issue is updated in place each day while the check keeps failing. Close it when `live.yml` passes again; a later failure opens a new one.

### `upstream-change`

Someone corrected one of the specs. Read the diff, decide whether it matters, and either merge the repair pull request or run `check_upstream.py --update` yourself to accept the new baseline. Then close the issue.

### Reviewing a repair pull request

The agent worked from the issue text only. It had no access to the live API, no push access and no credentials, and the workflow refuses changes to `.github/`, `CLAUDE.md`, this file, the licence and the version. What it cannot do is prove its fix is right. Before merging:

```bash
gh pr checkout <number>
uv run ruff check . && uv run mypy && uv run pytest
export BELI_SESSION_FILE=~/.config/beli/ci-session.json
uv run pytest -m live -v
uv run python scripts/snapshot_shapes.py --check
```

If the shapes still differ, record them (`snapshot_shapes.py` without `--check`), read the diff, and commit it to the branch.

To get another attempt on the same issue: Actions → Repair → Run workflow, with the issue number. It force-pushes `repair/issue-N` and updates the open pull request.

### Repair pull requests and CI

GitHub does not start workflows for pull requests opened with the built-in token, so `ci.yml` will not run on a repair pull request by default. The repair run does execute ruff, mypy and pytest itself and opens the pull request as a draft if they fail. To get the normal CI checks as well, either close and reopen the pull request, or create the `REPAIR_TOKEN` secret described above.

## Cutting a release

1. `main` is green, and the latest "Live API check" run passed.
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

7. Approve the `pypi` environment when `release.yml` asks. It builds and publishes with trusted publishing.
8. Check `pip install beli==0.2.0` in a clean environment, then paste the changelog entry into the GitHub release notes.
