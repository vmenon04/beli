# beli

Unofficial, read-only Python client and exporter for the Beli restaurant app.

Read [CONTRIBUTING.md](CONTRIBUTING.md) first: it has the checks, the ground rules, the project layout and how to add or fix an endpoint. The rules below are in addition to it.

1. **Never run anything against the live Beli API.** That means `pytest -m live`, `scripts/snapshot_shapes.py`, the `beli` CLI, and any ad hoc request to a Beli host. Only a person runs these, or CI with its secrets.
2. **No AI attribution.** No `Co-Authored-By` trailers, no "generated with" footers, no session links, no mention of assistants or tools in commit messages, PR text, comments or files.
3. **Do not merge, tag, publish, or change `src/beli/_version.py`** unless asked.
4. **Keep every request a GET.** If a fix seems to need a write, stop and say so.
5. **Use American English** in code, docs and commit messages.
