from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import respx

from beli import Beli
from beli._constants import HOST_API
from beli.cli import main

from .conftest import make_jwt


def _export(api: respx.MockRouter):  # type: ignore[no-untyped-def]
    return Beli("me@example.com", "pw", min_interval=0).export()


def test_rated_places_join(api: respx.MockRouter) -> None:
    exp = _export(api)
    rows = exp.rated_places()
    res = [r for r in rows if r["category"] == "RES"]
    assert [(r["rank"], r["name"]) for r in res] == [(1, "Pizzeria Toro"), (2, "Mateo")]
    mateo = res[1]
    assert mateo["note"] == "Get the tapas"
    assert mateo["photos"] == ["https://photos2.beliapp.cloud/a.jpg"]
    assert mateo["guides"] == ["Date night in Durham"]
    assert mateo["visit_dates"] == ["2025-04-30", "2025-01-02"]
    assert exp.want_to_try()[0]["name"] == "Lucky's"
    assert exp.warnings == []


def test_optional_parts_fail_softly(api: respx.MockRouter) -> None:
    api.get(f"{HOST_API}/api/user-business-photos/").respond(400, text="nope")
    exp = _export(api)
    assert exp.photos == []
    assert len(exp.warnings) == 1 and exp.warnings[0].startswith("photos:")


def test_json(api: respx.MockRouter, tmp_path: Path) -> None:
    (path,) = _export(api).write(tmp_path / "out.json")
    data = json.loads(path.read_text())
    assert data["schema"] == "beli-export/1"
    assert len(data["rated"]) == 3
    assert data["guides"][0]["business_ids"] == [1]
    assert data["averages"]["cuisines"][0]["value"] == "Thai"
    assert len(data["raw"]["rankings"]) == 3


def test_csv(api: respx.MockRouter, tmp_path: Path) -> None:
    rated, want = _export(api).write(tmp_path / "beli.csv")
    rows = list(csv.DictReader(rated.open()))
    assert rows[0]["name"] == "Pizzeria Toro"
    assert rows[1]["cuisines"] == "Thai"
    assert rows[1]["visit_dates"] == "2025-04-30; 2025-01-02"
    assert want.name == "beli-want-to-try.csv"
    assert next(csv.DictReader(want.open()))["name"] == "Lucky's"


def test_sqlite(api: respx.MockRouter, tmp_path: Path) -> None:
    (path,) = _export(api).write(tmp_path / "beli.db")
    con = sqlite3.connect(path)
    rated = con.execute("SELECT category, rank, name, note FROM rated").fetchall()
    assert rated[0] == ("BAR", 1, "Arcana", None)
    assert ("RES", 2, "Mateo", "Get the tapas") in rated
    assert con.execute("SELECT count(*) FROM visits").fetchone() == (3,)
    assert con.execute("SELECT count(*) FROM want_to_try").fetchone() == (1,)
    assert con.execute("SELECT count(*) FROM places").fetchone() == (4,)
    # rewriting replaces the file
    _export(api).write(path)


def test_cli_export(api: respx.MockRouter, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    session = tmp_path / "session.json"

    def run(*args: str) -> int:
        return main(["--session", str(session), "--interval", "0", *args])

    assert run("login", "--token", make_jwt(3600, kind="refresh")) == 0
    assert "Logged in as @vasu" in capsys.readouterr().out
    out = tmp_path / "x.db"
    assert run("export", "-f", "sqlite", "-o", str(out)) == 0
    printed = capsys.readouterr().out
    assert "Exported 3 ranked places (1 with notes), 1 want-to-try, 1 guides, 1 photos" in printed
    assert out.exists()
    assert run("rankings", "-n", "1") == 0
    assert "Pizzeria Toro" in capsys.readouterr().out
    assert run("logout") == 0
    assert not session.exists()


def test_cli_without_session(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["--session", str(tmp_path / "none.json"), "whoami"]) == 2
    assert "beli login" in capsys.readouterr().err
