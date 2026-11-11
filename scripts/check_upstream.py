"""Report upstream spec changes to the endpoints this package uses.

    python scripts/check_upstream.py             # compare, exit 1 on any change
    python scripts/check_upstream.py --update    # accept the current specs as the baseline

Fetches the OpenAPI specs published by horse-3903/beli-api-spec and
ProjectBarks/beli-api from GitHub (never the Beli API), picks out the
endpoints built in ``beli._endpoints`` plus login, refresh and host discovery,
and compares three things with ``tests/upstream/<repo>.json``: the path
template, the required parameters, and the shape of the 200 response.

It also lists required query parameters that this package does not send,
which is a bug here or a mistake upstream, and worth knowing either way.

Exit codes: 0 no change, 1 changes (printed as Markdown), 2 a spec could not
be fetched or read.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

from _drift import Shape, diff_shapes
from beli import _endpoints as ep
from beli._constants import HOSTS_PATH
from beli._session import Request

ROOT = Path(__file__).resolve().parent.parent
BASELINES = ROOT / "tests" / "upstream"

SOURCES = {
    "horse-3903/beli-api-spec": (
        "https://raw.githubusercontent.com/horse-3903/beli-api-spec/main/beli-openapi.json"
    ),
    "ProjectBarks/beli-api": (
        "https://raw.githubusercontent.com/ProjectBarks/beli-api/main/openapi/beli.bundled.yaml"
    ),
}

USER, NUMBER = "USER", 424242
"""Stand-ins passed to the builders. They only need to be recognisable in a path."""

Used = dict[str, tuple[str, str, list[str]]]
"""Label to (method, concrete path, query parameters this package sends)."""


def used_endpoints() -> Used:
    """Every endpoint the package can call, from the builders themselves."""
    requests: list[Request[Any]] = [
        ep.me(),
        ep.member(USER),
        ep.categories(USER),
        ep.rank_count(USER),
        ep.ranked_this_year(USER, 2025),
        ep.app_rank(USER),
        ep.streak(USER),
        ep.rankings(USER, "RES"),
        ep.scores(USER),
        ep.score_averages(USER),
        ep.visit_dates(USER, NUMBER),
        ep.notes(USER, NUMBER),
        ep.photos(USER),
        ep.bookmarks(USER, "RES"),
        ep.guides(USER),
        ep.guide_items(USER),
        ep.guide(USER, NUMBER),
        ep.followers(USER),
        ep.following(USER),
        ep.search(USER, "term", "city", (0.0, 0.0)),
        ep.business_hours(NUMBER),
        ep.trending(USER, "RES"),
    ]
    used: Used = {
        "POST /api/token/": ("POST", "/api/token/", []),
        "POST /api/token/refresh/": ("POST", "/api/token/refresh/", []),
        f"GET {HOSTS_PATH}": ("GET", HOSTS_PATH, []),
    }
    for request in requests:
        shown = request.path.replace(USER, "{user}").replace(str(NUMBER), "{id}")
        used[f"{request.method} {shown}"] = (
            request.method,
            request.path,
            sorted(request.params or {}),
        )
    return used


def _resolve(
    node: Any, spec: dict[str, Any], seen: tuple[str, ...] = ()
) -> tuple[Any, tuple[str, ...]]:
    """Follow local ``$ref``s. Returns ``({}, seen)`` for a cycle or a ref that leads nowhere."""
    while isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        if ref in seen or not ref.startswith("#/"):
            return {}, seen
        seen = (*seen, ref)
        node = spec
        for part in ref[2:].split("/"):
            node = (
                node.get(part.replace("~1", "/").replace("~0", "~"), {})
                if isinstance(node, dict)
                else {}
            )
    return node, seen


_TYPES = {"integer": "number", "number": "number", "string": "string", "boolean": "boolean"}


def schema_shape(schema: Any, spec: dict[str, Any]) -> Shape:
    """Flatten an OpenAPI schema into the same path -> types form as ``_drift.shape_of``."""
    seen_types: dict[str, set[str]] = {}

    def walk(node: Any, path: str, refs: tuple[str, ...], depth: int) -> None:
        node, refs = _resolve(node, spec, refs)
        types = seen_types.setdefault(path, set())
        if not isinstance(node, dict) or depth > 12:
            return
        declared = node.get("type")
        for name in declared if isinstance(declared, list) else [declared]:
            if name in _TYPES:
                types.add(_TYPES[name])
            elif name in ("object", "array", "null"):
                types.add(name)
        if node.get("nullable"):
            types.add("null")
        for combiner in ("allOf", "anyOf", "oneOf"):
            for option in node.get(combiner) or []:
                walk(option, path, refs, depth + 1)
        if isinstance(node.get("properties"), dict):
            types.add("object")
            for name, child in node["properties"].items():
                walk(child, f"{path}.{name}", refs, depth + 1)
        if "items" in node:
            types.add("array")
            walk(node["items"], f"{path}[]", refs, depth + 1)

    walk(schema, "$", (), 0)
    return {path: sorted(types) or ["any"] for path, types in sorted(seen_types.items())}


def _find(
    spec: dict[str, Any], method: str, path: str
) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
    """The spec's (template, path item, operation) for a concrete path. Most literal match wins."""
    best: tuple[int, str, dict[str, Any], dict[str, Any]] | None = None
    for template, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict) or not isinstance(item.get(method.lower()), dict):
            continue
        pattern = "".join(
            "[^/]+" if part.startswith("{") else re.escape(part)
            for part in re.split(r"(\{[^}]*\})", template)
        )
        if re.fullmatch(pattern, path):
            literal = len(re.sub(r"\{[^}]*\}", "", template))
            if best is None or literal > best[0]:
                best = (literal, template, item, item[method.lower()])
    return best[1:] if best else None


def digest(spec: dict[str, Any], used: Used) -> dict[str, dict[str, Any]]:
    """What a spec says about each endpoint we use, reduced to what we compare."""
    out: dict[str, dict[str, Any]] = {}
    for name, (method, path, sent) in used.items():
        found = _find(spec, method, path)
        if found is None:
            out[name] = {"path": None}
            continue
        template, item, operation = found
        required = set()
        for raw in [*(item.get("parameters") or []), *(operation.get("parameters") or [])]:
            param, _ = _resolve(raw, spec)
            if isinstance(param, dict) and param.get("required"):
                required.add(f"{param.get('in')}:{param.get('name')}")
        responses = operation.get("responses") or {}
        ok, _ = _resolve(responses.get("200") or responses.get(200) or {}, spec)
        schema = ((ok.get("content") or {}).get("application/json") or {}).get("schema")
        unsent = sorted(r for r in required if r.startswith("query:") and r[6:] not in sent)
        out[name] = {
            "path": template,
            "required": sorted(required),
            "required_but_not_sent": unsent,
            "response": schema_shape(schema, spec) if schema is not None else None,
        }
    return out


def compare(old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]]) -> list[str]:
    """Markdown lines for every difference between two digests. Empty means none."""
    out: list[str] = []
    for name in sorted({*old, *new}):
        before, after = old.get(name), new.get(name)
        lines: list[str] = []
        if before is None:
            lines.append("- New in this package; no baseline yet.")
        elif after is None:
            lines.append("- No longer used by this package; still in the baseline.")
        elif before != after:
            if before.get("path") != after.get("path"):
                lines.append(f"- Path: `{before.get('path')}` is now `{after.get('path')}`")
            for key, what in (
                ("required", "Required parameters"),
                ("required_but_not_sent", "Required parameters this package does not send"),
            ):
                gone = sorted(set(before.get(key) or []) - set(after.get(key) or []))
                added = sorted(set(after.get(key) or []) - set(before.get(key) or []))
                if gone or added:
                    change = [f"added `{a}`" for a in added] + [f"removed `{g}`" for g in gone]
                    lines.append(f"- {what}: {', '.join(change)}")
            shapes = before.get("response"), after.get("response")
            if shapes[0] != shapes[1]:
                diff = diff_shapes(shapes[0] or {}, shapes[1] or {}, "response")
                diff[:2] = ["--- baseline", "+++ upstream"]
                lines += ["- Response shape:", "", "```diff", *diff, "```"]
        if lines:
            out += [f"### {name}", "", *lines, ""]
    return out


def parse_spec(text: str) -> dict[str, Any]:
    """OpenAPI as JSON or YAML. Raises ``ValueError`` if it is neither, or has no paths."""
    try:
        spec = json.loads(text)
    except ValueError:
        try:
            spec = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError("not JSON or YAML") from exc
    if not isinstance(spec, dict) or not isinstance(spec.get("paths"), dict):
        raise ValueError("no `paths` in the document")
    return spec


def fetch(url: str) -> str:
    response = httpx.get(url, follow_redirects=True, timeout=60)
    response.raise_for_status()
    return response.text


def baseline_path(directory: Path, source: str) -> Path:
    return directory / f"{source.replace('/', '__')}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--update", action="store_true", help="write the baselines")
    parser.add_argument("--dir", type=Path, default=BASELINES, help="where the baselines live")
    parser.add_argument("--report", type=Path, help="also write the result here as Markdown")
    args = parser.parse_args(argv)

    used = used_endpoints()
    report: list[str] = []
    code = 0
    for source, url in SOURCES.items():
        try:
            current = digest(parse_spec(fetch(url)), used)
        except (httpx.HTTPError, ValueError) as exc:
            report += [f"## {source}", "", f"Could not read {url}: {type(exc).__name__}: {exc}", ""]
            code = 2
            continue
        path = baseline_path(args.dir, source)
        if args.update:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"source": url, "endpoints": current}, indent=2) + "\n")
            missing = sum(1 for d in current.values() if d["path"] is None)
            report.append(
                f"wrote {path.name}: {len(current) - missing} endpoints, {missing} not in this spec"
            )
            continue
        if not path.exists():
            report += [f"## {source}", "", f"No baseline at `{path.name}`. Run with --update.", ""]
            code = code or 1
            continue
        changes = compare(json.loads(path.read_text())["endpoints"], current)
        if changes:
            report += [f"## {source}", "", f"Spec: {url}", "", *changes]
            code = code or 1
    if not report:
        report = [f"No upstream changes to the {len(used)} endpoints this package uses."]

    text = "\n".join(report).rstrip() + "\n"
    print(text, end="")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
