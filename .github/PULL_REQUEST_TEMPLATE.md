## What this changes

<!-- What changed and why. Link the issue if there is one. -->

## Checklist

- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest` passes
- [ ] Every request is still a GET (the package is read-only)
- [ ] No tokens, account data or real response bodies in the diff
- [ ] Ran the live tests (`uv run pytest -m live`), or explained why not
- [ ] Added a `CHANGELOG.md` entry if users will notice the change
