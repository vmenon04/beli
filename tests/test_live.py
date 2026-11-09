"""Read-only checks against the real API. Skipped unless run with ``-m live``.

    beli login
    pytest -m live

These only read. They exist to catch Beli changing response shapes.
"""

from __future__ import annotations

import pytest

from beli import Beli
from beli._auth import default_session_path

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def beli() -> Beli:
    import os

    session = os.environ.get("BELI_LIVE_SESSION") or str(default_session_path())
    return Beli.from_session(session, min_interval=2.0)


def test_me(beli: Beli) -> None:
    assert beli.me().id == beli.user_id


def test_rankings_parse(beli: Beli) -> None:
    rankings = beli.rankings.list()
    if rankings:
        assert rankings[0].business.name
        assert rankings[0].score is not None


def test_categories_and_notes(beli: Beli) -> None:
    assert any(c.code == "RES" for c in beli.categories())
    beli.notes.list()


def test_export_round_trip(beli: Beli, tmp_path) -> None:  # type: ignore[no-untyped-def]
    export = beli.export(["RES"])
    export.write(tmp_path / "x.db")
    assert export.warnings == [], export.warnings
