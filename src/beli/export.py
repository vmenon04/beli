"""Export everything on an account and write it as JSON, CSV or SQLite."""

from __future__ import annotations

import csv
import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._version import __version__
from .models import Bookmark, Guide, GuideItem, Note, Photo, Ranking, ScoreAverages, User

FORMATS = ("json", "csv", "sqlite")


@dataclass
class Export:
    user: User
    rankings: list[Ranking] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    photos: list[Photo] = field(default_factory=list)
    bookmarks: list[Bookmark] = field(default_factory=list)
    guides: list[Guide] = field(default_factory=list)
    guide_items: list[GuideItem] = field(default_factory=list)
    averages: ScoreAverages | None = None
    exported_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    warnings: list[str] = field(default_factory=list)

    def rated_places(self) -> list[dict[str, Any]]:
        """One flat row per ranking, with its note, photos and rank position joined in."""
        notes = {n.business: n.value for n in self.notes}
        photos: dict[int, list[str]] = defaultdict(list)
        for p in sorted(self.photos, key=lambda p: (p.order or 0, p.id)):
            photos[p.business].append(p.image)
        guide_names = {g.id: g.full_title or g.name or str(g.id) for g in self.guides}
        in_guides: dict[int, list[str]] = defaultdict(list)
        for item in self.guide_items:
            in_guides[item.business].append(guide_names.get(item.guide, str(item.guide)))

        by_category: dict[str, list[Ranking]] = defaultdict(list)
        for r in self.rankings:
            by_category[r.category].append(r)

        rows = []
        for category, items in by_category.items():
            items = sorted(
                items, key=lambda r: r.score if r.score is not None else -1, reverse=True
            )
            for position, r in enumerate(items, start=1):
                b = r.business
                rows.append(
                    {
                        "rank": position,
                        "category": category,
                        "score": r.score,
                        "name": b.name,
                        "business_id": b.id,
                        "neighborhood": b.neighborhood,
                        "city": b.city,
                        "country": b.country,
                        "cuisines": b.cuisines,
                        "price": b.price_symbol,
                        "lat": b.lat,
                        "lng": b.lng,
                        "note": notes.get(b.id),
                        "visit_dates": [d.isoformat() for d in r.visit_dates],
                        "latest_visit": r.latest_visit_date.isoformat()
                        if r.latest_visit_date
                        else None,
                        "ranked_at": r.created_dt.isoformat() if r.created_dt else None,
                        "photos": photos.get(b.id, []),
                        "guides": in_guides.get(b.id, []),
                        "website": b.website,
                        "google_place_id": b.place_id,
                        "beli_link": b.quick_link,
                        "ranking_id": r.id,
                    }
                )
        return rows

    def want_to_try(self) -> list[dict[str, Any]]:
        rows = []
        for bm in self.bookmarks:
            b = bm.business
            rows.append(
                {
                    "name": b.name,
                    "business_id": b.id,
                    "category": bm.category,
                    "neighborhood": b.neighborhood,
                    "city": b.city,
                    "country": b.country,
                    "cuisines": b.cuisines,
                    "price": b.price_symbol,
                    "lat": b.lat,
                    "lng": b.lng,
                    "added_at": bm.start_dt.isoformat() if bm.start_dt else None,
                    "website": b.website,
                    "google_place_id": b.place_id,
                    "beli_link": b.quick_link,
                }
            )
        return rows

    def to_dict(self) -> dict[str, Any]:
        """Normalized rows plus the raw API objects, so nothing Beli sent is lost."""

        def dump(items: Iterable[Any]) -> list[Any]:
            return [i.model_dump(mode="json", by_alias=True) for i in items]

        return {
            "schema": "beli-export/1",
            "generator": f"beli-python {__version__}",
            "exported_at": self.exported_at.isoformat(),
            "user": self.user.model_dump(mode="json"),
            "rated": self.rated_places(),
            "want_to_try": self.want_to_try(),
            "guides": [
                {
                    **g.model_dump(mode="json"),
                    "business_ids": [i.business for i in self.guide_items if i.guide == g.id],
                }
                for g in self.guides
            ],
            "averages": self.averages.model_dump(mode="json") if self.averages else None,
            "raw": {
                "rankings": dump(self.rankings),
                "notes": dump(self.notes),
                "photos": dump(self.photos),
                "bookmarks": dump(self.bookmarks),
            },
            "warnings": self.warnings,
        }

    def write(self, path: str | Path, fmt: str | None = None) -> list[Path]:
        """Write in ``fmt`` (guessed from the extension if omitted). Returns files written."""
        path = Path(path)
        fmt = fmt or {".json": "json", ".db": "sqlite", ".sqlite": "sqlite", ".csv": "csv"}.get(
            path.suffix.lower(), "json"
        )
        if fmt == "json":
            return [write_json(self, path)]
        if fmt == "csv":
            return write_csv(self, path)
        if fmt == "sqlite":
            return [write_sqlite(self, path)]
        raise ValueError(f"Unknown format {fmt!r}; use one of {', '.join(FORMATS)}")


def write_json(export: Export, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(export.to_dict(), indent=2, ensure_ascii=False) + "\n")
    return path


def _flat(value: Any) -> Any:
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return value


def write_csv(export: Export, path: Path) -> list[Path]:
    """Writes ``<stem>.csv`` (rated places) and ``<stem>-want-to-try.csv``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rated = path if path.suffix else path.with_suffix(".csv")
    want = rated.with_name(f"{rated.stem}-want-to-try.csv")
    written = []
    for target, rows in ((rated, export.rated_places()), (want, export.want_to_try())):
        with target.open("w", newline="", encoding="utf-8") as fh:
            if rows:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows({k: _flat(v) for k, v in row.items()} for row in rows)
        written.append(target)
    return written


SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE places (
    id INTEGER PRIMARY KEY, name TEXT, neighborhood TEXT, city TEXT, country TEXT,
    cuisines TEXT, price INTEGER, lat REAL, lng REAL, website TEXT, phone TEXT,
    google_place_id TEXT, beli_link TEXT
);
CREATE TABLE rankings (
    id INTEGER PRIMARY KEY, place_id INTEGER REFERENCES places(id), category TEXT,
    rank INTEGER, score REAL, ranked_at TEXT, latest_visit TEXT
);
CREATE TABLE visits (place_id INTEGER REFERENCES places(id), category TEXT, visit_date TEXT);
CREATE TABLE notes (place_id INTEGER PRIMARY KEY REFERENCES places(id), text TEXT, written_at TEXT);
CREATE TABLE photos (
    id INTEGER PRIMARY KEY, place_id INTEGER REFERENCES places(id), url TEXT,
    thumbnail TEXT, description TEXT, taken_at TEXT
);
CREATE TABLE want_to_try (place_id INTEGER REFERENCES places(id), category TEXT, added_at TEXT);
CREATE TABLE guides (id INTEGER PRIMARY KEY, title TEXT, description TEXT, audience TEXT, city TEXT);
CREATE TABLE guide_places (guide_id INTEGER REFERENCES guides(id), place_id INTEGER);
CREATE VIEW rated AS
    SELECT r.category, r.rank, r.score, p.name, p.neighborhood, p.city, p.cuisines,
           n.text AS note, r.latest_visit, r.ranked_at, p.id AS place_id
    FROM rankings r JOIN places p ON p.id = r.place_id
    LEFT JOIN notes n ON n.place_id = p.id
    ORDER BY r.category, r.rank;
"""


def write_sqlite(export: Export, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    try:
        con.executescript(SCHEMA)
        con.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [
                ("schema", "beli-export/1"),
                ("exported_at", export.exported_at.isoformat()),
                ("username", export.user.username or ""),
                ("user_id", export.user.id),
            ],
        )
        places = {r.business.id: r.business for r in export.rankings}
        places.update({b.business.id: b.business for b in export.bookmarks})
        con.executemany(
            "INSERT INTO places VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    b.id,
                    b.name,
                    b.neighborhood,
                    b.city,
                    b.country,
                    ", ".join(b.cuisines),
                    b.price,
                    b.lat,
                    b.lng,
                    b.website,
                    b.phone_number,
                    b.place_id,
                    b.quick_link,
                )
                for b in places.values()
            ],
        )
        for row in export.rated_places():
            con.execute(
                "INSERT INTO rankings VALUES (?,?,?,?,?,?,?)",
                (
                    row["ranking_id"],
                    row["business_id"],
                    row["category"],
                    row["rank"],
                    row["score"],
                    row["ranked_at"],
                    row["latest_visit"],
                ),
            )
            con.executemany(
                "INSERT INTO visits VALUES (?,?,?)",
                [(row["business_id"], row["category"], d) for d in row["visit_dates"]],
            )
        con.executemany(
            "INSERT OR REPLACE INTO notes VALUES (?,?,?)",
            [
                (n.business, n.value, n.start_dt.isoformat() if n.start_dt else None)
                for n in export.notes
            ],
        )
        con.executemany(
            "INSERT INTO photos VALUES (?,?,?,?,?,?)",
            [
                (
                    p.id,
                    p.business,
                    p.image,
                    p.thumbnail,
                    p.description,
                    p.created_dt.isoformat() if p.created_dt else None,
                )
                for p in export.photos
            ],
        )
        con.executemany(
            "INSERT INTO want_to_try VALUES (?,?,?)",
            [
                (b.business.id, b.category, b.start_dt.isoformat() if b.start_dt else None)
                for b in export.bookmarks
            ],
        )
        con.executemany(
            "INSERT INTO guides VALUES (?,?,?,?,?)",
            [
                (g.id, g.full_title or g.name, g.description, g.audience, g.city)
                for g in export.guides
            ],
        )
        con.executemany(
            "INSERT INTO guide_places VALUES (?,?)",
            [(i.guide, i.business) for i in export.guide_items],
        )
        con.commit()
    finally:
        con.close()
    return path
