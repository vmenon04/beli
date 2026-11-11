"""Scrubbing, recording (against the mocked API) and the recorded fixtures themselves."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import respx

import record_fixtures
from _drift import replay_export
from _scrub import FAKE_UUID, Scrubber, pattern_leaks
from beli._auth import Tokens, save_tokens

from .conftest import USER_ID, make_jwt

FIXTURES = Path(__file__).parent / "fixtures"


def load(directory: Path) -> dict[str, dict[str, Any]]:
    return {p.stem: json.loads(p.read_text()) for p in sorted(directory.glob("*.json"))}


def test_scrubber_replaces_everything_personal() -> None:
    raw = {
        "id": 48213,
        "user": USER_ID,
        "business": {
            "id": 777,
            "name": "Mateo Bar de Tapas",
            "lat": 35.9966,
            "lng": -78.9018,
            "website": "https://mateotapas.com/menu",
            "phone_number": "+19195550100",
            "status": "ACTIVE",
            "city": "DURHAM",
            "cuisines": ["Spanish", "Tapas"],
            "price": 2,
            "place_id": "ChIJN1t_tDeuEmsRUsoyG83frY4",
        },
        "category": "RES",
        "score": 8.4,
        "value": "Get the tapas, sit at the bar",
        "created_dt": "2025-05-01T20:00:00Z",
        "visit_dates": ["2025-04-30", "2025-01-02"],
        "access": make_jwt(),
        "email": "someone@gmail.com",
        "public": True,
        "borough": None,
        "by_business": {"777": {"count": 2}},
        "legacy_ref": 9876543210,
    }
    scrubber = Scrubber()
    out = scrubber.scrub(raw)
    assert scrubber.leaks(out) == []
    text = json.dumps(out)
    for secret in (
        "48213", "777", USER_ID, "Mateo", "35.99", "78.90", "mateotapas", "9195550100",
        "DURHAM", "Spanish", "ChIJ", "tapas", "2025", "eyJ", "gmail", "9876543210",
    ):  # fmt: skip
        assert secret not in text, secret
    # Kept: structure, codes, and numbers that are not ids.
    assert out["category"] == "RES" and out["business"]["status"] == "ACTIVE"
    assert (out["score"], out["business"]["price"], out["public"], out["borough"]) == (
        8.4,
        2,
        True,
        None,
    )
    assert set(out) == set(raw) and set(out["business"]) == set(raw["business"])
    assert out["user"].startswith(FAKE_UUID)
    assert out["business"]["website"].startswith("https://example.com/")
    # The same real id maps to the same fake id wherever it turns up, including as a key.
    assert list(out["by_business"]) == [str(out["business"]["id"])]
    assert scrubber.scrub({"business": 777}) == {"business": out["business"]["id"]}


def test_scrubber_truncates_lists_and_detects_leaks() -> None:
    scrubber = Scrubber(max_items=2)
    assert len(scrubber.scrub({"results": [{"id": i} for i in range(10)]})["results"]) == 2
    scrubber.scrub({"name": "Pizzeria Toro"})
    assert scrubber.leaks({"note": "went to Pizzeria Toro again"}) == [
        "1 original value(s) survive in the output"
    ]
    assert pattern_leaks("see https://beliapp.co/app/1") == [
        "contains a URL that is not example.com"
    ]
    assert pattern_leaks(USER_ID) == ["contains a real UUID"]
    assert pattern_leaks(f"https://example.com/x/1 {FAKE_UUID}000000000001 plain words") == []


def test_record_against_mock_then_replay(
    api: respx.MockRouter, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    session = tmp_path / "session.json"
    save_tokens(session, Tokens(access=make_jwt(), refresh=make_jwt(3600, kind="refresh")))
    out = tmp_path / "fixtures"
    code = record_fixtures.main(["--session", str(session), "--interval", "0", "--dir", str(out)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert sorted(p.name for p in out.glob("*.json")) == [
        "datauserbusinesstext-sparse.json",
        "get-bookmark.BAR.json",
        "get-bookmark.RES.json",
        "get-ranking.BAR.json",
        "get-ranking.RES.json",
        "score-average.USER.ALL.json",
        "user-business-photos.json",
        "user-guide-items.json",
        "user-guide.json",
        "user-setting.json",
        "user.logged-in.json",
    ]
    text = "".join(p.read_text() for p in out.glob("*.json"))
    for secret in (
        USER_ID, "Mateo", "Toro", "Arcana", "Lucky", "Get the tapas", "old note", "Durham",
        "beliapp", "35.99", "-78.9", "Vasu", "vasu", "Date night", "Thai", "9195550100",
    ):  # fmt: skip
        assert secret not in text, secret
    assert pattern_leaks(text) == []

    export = replay_export(load(out))
    assert export.warnings == []
    assert export.user.id == f"{FAKE_UUID}000000000001"
    rows = export.rated_places()
    assert len(rows) == 3
    # Joins survive scrubbing: one ranking still has its note, photo and guide.
    assert sum(1 for r in rows if r["note"] and r["photos"] and r["guides"]) == 1
    export.write(tmp_path / "x.db")
    con = sqlite3.connect(tmp_path / "x.db")
    assert con.execute("SELECT count(*) FROM rated").fetchone() == (3,)


def test_record_writes_nothing_on_failure(
    api: respx.MockRouter, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from beli._constants import HOST_API

    api.get(f"{HOST_API}/api/user-guide/").respond(500, text="secret body")
    session = tmp_path / "session.json"
    save_tokens(session, Tokens(access=make_jwt(), refresh=make_jwt(3600, kind="refresh")))
    out = tmp_path / "fixtures"
    assert (
        record_fixtures.main(["--session", str(session), "--interval", "0", "--dir", str(out)]) == 1
    )
    assert not out.exists()
    printed = capsys.readouterr().out
    assert "HTTP 500 from GET /api/user-guide/. Nothing written." in printed
    assert "secret body" not in printed


# The recorded fixtures in tests/fixtures. Skipped until scripts/record_fixtures.py has been run.

recorded = pytest.mark.skipif(
    not any(FIXTURES.glob("*.json")), reason="no recorded fixtures; run scripts/record_fixtures.py"
)


@recorded
def test_recorded_fixtures_hold_nothing_recognisable() -> None:
    for path in sorted(FIXTURES.glob("*.json")):
        assert pattern_leaks(path.read_text()) == [], path.name


@recorded
def test_recorded_fixtures_export(tmp_path: Path) -> None:
    export = replay_export(load(FIXTURES))
    assert export.warnings == []
    export.write(tmp_path / "x.json")
    export.write(tmp_path / "x.csv")
    export.write(tmp_path / "x.db")
