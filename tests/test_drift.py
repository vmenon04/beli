"""The drift scripts, run against the mocked API. Nothing here touches the network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import respx
import snapshot_shapes

from beli import Beli
from beli._auth import Tokens, save_tokens
from beli._constants import HOST_API

from .conftest import RANKINGS_RES, USER_ID, business, make_jwt
from _drift import describe, diff_shapes, exporter_calls, merge, shape_of


@pytest.fixture
def session(tmp_path: Path) -> Path:
    path = tmp_path / "session.json"
    save_tokens(path, Tokens(access=make_jwt(), refresh=make_jwt(3600, kind="refresh")))
    return path


def test_shape_has_names_and_types_but_no_values() -> None:
    data = {
        "results": [
            {"id": 1, "name": "Mateo", "score": 8.4, "tags": ["a"], "open": True, "note": None},
            {"id": 2, "name": "Toro", "score": 9, "tags": [], "note": "secret words"},
        ],
        "by_id": {"123": {"x": 1}, USER_ID: {"x": None}},
    }
    shape = shape_of(data)
    assert shape == {
        "$": ["object"],
        "$.by_id": ["object"],
        "$.by_id.*": ["object"],
        "$.by_id.*.x": ["null", "number"],
        "$.results": ["array"],
        "$.results[]": ["object"],
        "$.results[].id": ["number"],
        "$.results[].name": ["string"],
        "$.results[].note": ["null", "string"],
        "$.results[].open": ["boolean"],
        "$.results[].score": ["number"],
        "$.results[].tags": ["array"],
        "$.results[].tags[]": ["string"],
    }
    text = json.dumps(shape)
    for value in ("Mateo", "Toro", "secret", "8.4", "123", USER_ID):
        assert value not in text


def test_merge_and_diff() -> None:
    old = shape_of({"a": 1, "b": "x"})
    new = shape_of({"a": "1", "c": None})
    assert merge(old, new)["$.a"] == ["number", "string"]
    assert diff_shapes(old, old, "x.json") == []
    diff = "\n".join(diff_shapes(old, new, "x.json"))
    assert "-$.a: number" in diff and "+$.a: string" in diff
    assert "-$.b: string" in diff and "+$.c: null" in diff


def test_exporter_calls_cover_the_export(api: respx.MockRouter, session: Path) -> None:
    with Beli.from_session(session, min_interval=0) as beli:
        captures = list(exporter_calls(beli))
    assert [c.label for c in captures] == [
        "GET /api/api-hosts/",
        "GET /api/user/logged-in/",
        "GET /api/user-setting/",
        "GET /api/get-ranking/",
        "GET /api/get-ranking/",
        "GET /api/datauserbusinesstext-sparse/",
        "GET /api/user-business-photos/",
        "GET /api/get-bookmark/",
        "GET /api/get-bookmark/",
        "GET /api/user-guide/",
        "GET /api/user-guide-items/",
        "GET /api/score-average/{user}/ALL/",
    ]
    assert captures[-1].name == "score-average.USER.ALL"
    assert all(c.error is None and c.raw is not None for c in captures)
    assert captures[3].raw == RANKINGS_RES  # raw JSON, not models


def test_snapshot_write_then_check(
    api: respx.MockRouter, session: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shapes = tmp_path / "shapes"
    common = ["--session", str(session), "--interval", "0", "--dir", str(shapes)]
    assert snapshot_shapes.main(common) == 0
    files = sorted(p.name for p in shapes.glob("*.json"))
    assert "get-ranking.json" in files and "score-average.USER.ALL.json" in files
    assert len(files) == 10
    stored = "".join(p.read_text() for p in shapes.glob("*.json"))
    for value in ("Mateo", "Get the tapas", USER_ID, "photos2.beliapp.cloud", "Durham", "vasu"):
        assert value not in stored
    ranking = json.loads((shapes / "get-ranking.json").read_text())
    assert ranking["endpoint"] == "GET /api/get-ranking/"
    # RES and BAR are merged: visit_dates holds strings in one and objects in the other.
    assert ranking["shape"]["$.results[].visit_dates[]"] == ["object", "string"]

    capsys.readouterr()
    assert snapshot_shapes.main([*common, "--check"]) == 0
    assert "10 response shapes match" in capsys.readouterr().out


def test_snapshot_check_reports_drift_readably(
    api: respx.MockRouter, session: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shapes = tmp_path / "shapes"
    common = ["--session", str(session), "--interval", "0", "--dir", str(shapes)]
    assert snapshot_shapes.main(common) == 0

    row = {
        "id": 101,
        "business": business(1, "Renamed Secret Place"),
        "category": "RES",
        "score": "8.4",
        "rank_position": 1,
    }
    api.get(f"{HOST_API}/api/get-ranking/", params={"category": "RES"}).respond(
        json={"results": [row]}
    )
    api.get(f"{HOST_API}/api/user-business-photos/").respond(500, text="private body text")
    report = tmp_path / "out" / "report.md"
    capsys.readouterr()
    assert snapshot_shapes.main([*common, "--check", "--report", str(report)]) == 1
    out = capsys.readouterr().out
    assert out == report.read_text()
    assert "### GET /api/get-ranking/" in out
    assert "+$.results[].rank_position: number" in out
    assert "-$.results[].score: number" in out and "+$.results[].score: number | string" in out
    assert "- GET /api/user-business-photos/: HTTP 500 from GET /api/user-business-photos/" in out
    assert "Stored, but no response this run." in out
    for value in ("Renamed Secret Place", "private body text", USER_ID):
        assert value not in out


def test_parse_failure_is_reported_without_values(
    api: respx.MockRouter, session: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api.get(f"{HOST_API}/api/get-ranking/", params={"category": "RES"}).respond(
        json={"results": [{"id": "not-a-number-secret", "category": "RES"}]}
    )
    code = snapshot_shapes.main(
        ["--session", str(session), "--interval", "0", "--dir", str(tmp_path / "s")]
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "response no longer parses" in out and "0.id (int_parsing)" in out
    assert "0.business (missing)" in out and "stopped early" in out
    assert "not-a-number-secret" not in out


def test_unusable_session_is_reported_by_type_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = snapshot_shapes.main(["--session", str(tmp_path / "none.json"), "--check"])
    assert code == 1
    assert capsys.readouterr().out == "Could not read the API: AuthenticationError\n"


def test_describe_never_quotes_the_response(api: respx.MockRouter) -> None:
    api.get(f"{HOST_API}/api/user-business-photos/").respond(400, text="body with secrets")
    with pytest.raises(Exception) as info:
        Beli("me@example.com", "pw", min_interval=0).photos.list()
    assert describe(info.value, USER_ID) == "HTTP 400 from GET /api/user-business-photos/"
    assert describe(RuntimeError("secret detail")) == "RuntimeError"
