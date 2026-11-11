"""scripts/check_upstream.py against hand-made specs. Nothing here touches the network."""

from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

import check_upstream
from beli import _endpoints as ep

SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "components": {
        "parameters": {
            "Origin": {"name": "Origin", "in": "header", "required": True},
        },
        "schemas": {
            "Business": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                    "borough": {"nullable": True},
                    "parent": {"$ref": "#/components/schemas/Business"},
                },
            }
        },
    },
    "paths": {
        "/api/get-ranking/": {
            "get": {
                "parameters": [
                    {"$ref": "#/components/parameters/Origin"},
                    {"name": "user", "in": "query", "required": True},
                    {"name": "category", "in": "query", "required": True},
                    {"name": "business", "in": "query", "required": False},
                ],
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "results": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "score": {"type": "number"},
                                                    "business": {
                                                        "$ref": "#/components/schemas/Business"
                                                    },
                                                },
                                            },
                                        }
                                    },
                                }
                            }
                        }
                    }
                },
            },
            "post": {"responses": {}},
        },
        "/api/user-field-count/{uuid}/{field}/": {"get": {"responses": {}}},
        "/api/user-field-count/{uuid}/RANK/": {
            "get": {"parameters": [{"name": "uuid", "in": "path", "required": True}]}
        },
    },
}

RANKING = "GET /api/get-ranking/"
COUNT = "GET /api/user-field-count/{user}/RANK/"


def test_every_endpoint_builder_is_checked() -> None:
    builders = {
        name
        for name, fn in inspect.getmembers(ep, inspect.isfunction)
        if fn.__module__ == ep.__name__
        and str(inspect.signature(fn).return_annotation).startswith("Request[")
    }
    # raw_get has no fixed path, and note_text is the notes endpoint with another parser.
    builders -= {"raw_get", "note_text"}
    source = inspect.getsource(check_upstream.used_endpoints)
    missing = sorted(name for name in builders if f"ep.{name}(" not in source)
    assert not missing, f"add these builders to check_upstream.used_endpoints: {missing}"
    assert len(check_upstream.used_endpoints()) == len(builders) + 3


def test_committed_baselines_cover_the_endpoints_in_use() -> None:
    used = set(check_upstream.used_endpoints())
    for source in check_upstream.SOURCES:
        path = check_upstream.baseline_path(check_upstream.BASELINES, source)
        stored = set(json.loads(path.read_text())["endpoints"])
        assert stored == used, f"{path.name} is stale; run scripts/check_upstream.py --update"


def test_digest() -> None:
    found = check_upstream.digest(SPEC, check_upstream.used_endpoints())
    assert found[RANKING] == {
        "path": "/api/get-ranking/",
        "required": ["header:Origin", "query:category", "query:user"],
        "required_but_not_sent": [],
        "response": {
            "$": ["object"],
            "$.results": ["array"],
            "$.results[]": ["object"],
            "$.results[].business": ["object"],
            "$.results[].business.borough": ["null"],
            "$.results[].business.id": ["number"],
            "$.results[].business.name": ["string"],
            "$.results[].business.parent": ["any"],  # the cycle stops here
            "$.results[].score": ["number"],
        },
    }
    # The more literal template wins over /{uuid}/{field}/.
    assert found[COUNT]["path"] == "/api/user-field-count/{uuid}/RANK/"
    assert found[COUNT]["required"] == ["path:uuid"]
    assert found["GET /api/user-business-photos/"] == {"path": None}


def test_compare_reports_path_params_and_shape() -> None:
    used = check_upstream.used_endpoints()
    old = check_upstream.digest(SPEC, used)
    assert check_upstream.compare(old, old) == []

    spec = copy.deepcopy(SPEC)
    get = spec["paths"]["/api/get-ranking/"]["get"]
    get["parameters"][3]["required"] = True  # business
    get["parameters"].append({"name": "version", "in": "query", "required": True})
    del get["parameters"][2]  # category
    items = get["responses"]["200"]["content"]["application/json"]["schema"]["properties"]
    items["results"]["items"]["properties"]["score"] = {"type": "string"}
    items["results"]["items"]["properties"]["rank"] = {"type": "integer"}
    spec["paths"]["/api/user-field-count/{id}/RANK/"] = spec["paths"].pop(
        "/api/user-field-count/{uuid}/RANK/"
    )
    text = "\n".join(check_upstream.compare(old, check_upstream.digest(spec, used)))
    assert f"### {RANKING}" in text and f"### {COUNT}" in text
    assert "added `query:business`, added `query:version`, removed `query:category`" in text
    assert "does not send: added `query:business`, added `query:version`" in text
    assert "+$.results[].rank: number" in text
    assert "-$.results[].score: number" in text and "+$.results[].score: string" in text
    assert "`/api/user-field-count/{uuid}/RANK/` is now `/api/user-field-count/{id}/RANK/`" in text
    assert text.count("###") == 2  # nothing else is reported


def test_main_exit_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    served = {"spec": json.dumps(SPEC)}
    monkeypatch.setattr(check_upstream, "fetch", lambda url: served["spec"])
    args = ["--dir", str(tmp_path)]

    assert check_upstream.main(args) == 1
    assert "No baseline" in capsys.readouterr().out
    assert check_upstream.main([*args, "--update"]) == 0
    assert len(list(tmp_path.glob("*.json"))) == len(check_upstream.SOURCES)
    capsys.readouterr()
    assert check_upstream.main(args) == 0
    assert "No upstream changes to the 25 endpoints" in capsys.readouterr().out

    changed = copy.deepcopy(SPEC)
    del changed["paths"]["/api/get-ranking/"]
    served["spec"] = json.dumps(changed)
    report = tmp_path / "r" / "report.md"
    assert check_upstream.main([*args, "--report", str(report)]) == 1
    out = capsys.readouterr().out
    assert out == report.read_text()
    assert "## horse-3903/beli-api-spec" in out and "## ProjectBarks/beli-api" in out
    assert "Path: `/api/get-ranking/` is now `None`" in out

    served["spec"] = "paths: [not, a, mapping]"
    assert check_upstream.main(args) == 2

    def down(url: str) -> str:
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(check_upstream, "fetch", down)
    assert check_upstream.main(args) == 2
    assert "Could not read" in capsys.readouterr().out


def test_parse_spec_reads_yaml() -> None:
    spec = check_upstream.parse_spec("openapi: 3.0.0\npaths:\n  /api/x/:\n    get: {}\n")
    assert list(spec["paths"]) == ["/api/x/"]
    with pytest.raises(ValueError, match="no `paths`"):
        check_upstream.parse_spec("[1, 2]")
