"""Read-only checks against the real API. Skipped unless run with ``-m live``.

    beli login
    pytest -m live

These only read. They exist to catch Beli changing response shapes.
"""

from __future__ import annotations

import itertools

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


def test_ranking_order(beli: Beli) -> None:
    """Answers the TODO on ``beli._endpoints.rankings``. Reports counts only, never values."""
    scores = [r.score for r in beli.rankings.list() if r.score is not None]
    ties = len(scores) - len(set(scores))
    if len(scores) < 3:
        pytest.skip(f"only {len(scores)} scored rankings; need 3 or more to say anything")
    out_of_order = sum(1 for a, b in itertools.pairwise(scores) if a < b)
    assert out_of_order == 0, (
        f"/api/get-ranking/ is NOT best-first: {out_of_order} of {len(scores) - 1} adjacent "
        f"pairs ascend ({ties} tied scores). The API order is not the rank order, so "
        'sort="score" is needed for a ranked list. Record that on the TODO and drop this assert.'
    )
    if ties == 0:
        pytest.skip("best-first confirmed, but this account has no tied scores to check tie order")


def test_categories_and_notes(beli: Beli) -> None:
    assert any(c.code == "RES" for c in beli.categories())
    beli.notes.list()


def test_export_round_trip(beli: Beli, tmp_path) -> None:  # type: ignore[no-untyped-def]
    export = beli.export(["RES"])
    export.write(tmp_path / "x.db")
    assert export.warnings == [], export.warnings
