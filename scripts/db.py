"""SQLite storage. Append-only availability so we keep every snapshot over time.

    showings     -- one row per screening (upserted)
    seats        -- static per-seat layout for a showing (upserted)
    availability -- (showing, seat, captured_at) time series -- INSERT only
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from adapters.base import Seat, Showing

DEFAULT_DB = Path(__file__).resolve().parent.parent / "seats.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS showings (
    id             TEXT PRIMARY KEY,
    theater        TEXT NOT NULL,
    auditorium     TEXT NOT NULL,
    film           TEXT NOT NULL,
    fmt            TEXT NOT NULL,
    start_time     TEXT NOT NULL,
    checkout_url   TEXT NOT NULL,
    screen_center_x REAL,
    screen_y       REAL
);

CREATE TABLE IF NOT EXISTS seats (
    showing_id TEXT NOT NULL,
    seat_id    TEXT NOT NULL,
    section    TEXT NOT NULL,
    row        TEXT NOT NULL,
    num        INTEGER NOT NULL,
    x          REAL NOT NULL,
    y          REAL NOT NULL,
    seat_type  TEXT NOT NULL,
    PRIMARY KEY (showing_id, seat_id),
    FOREIGN KEY (showing_id) REFERENCES showings(id)
);

CREATE TABLE IF NOT EXISTS availability (
    showing_id  TEXT NOT NULL,
    seat_id     TEXT NOT NULL,
    captured_at TEXT NOT NULL,   -- ISO 8601, passed in by the caller
    status      TEXT NOT NULL,
    PRIMARY KEY (showing_id, seat_id, captured_at)
);

CREATE INDEX IF NOT EXISTS idx_avail_time ON availability(showing_id, captured_at);
"""


def connect(db_path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10)
    # WAL lets the ingest daemon write while the API reads concurrently (no locks);
    # the API reconnects per request so it sees fresh data with no restart.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    return conn


def prune_stale(conn: sqlite3.Connection) -> int:
    """Delete placeholder/seed showings (empty checkout_url or *SEED* ids) + their
    seats/availability. Regal rows (real deep-links) are kept."""
    where = "checkout_url='' OR id LIKE '%SEED%'"
    ids = [r[0] for r in conn.execute(f"SELECT id FROM showings WHERE {where}")]
    conn.executemany("DELETE FROM availability WHERE showing_id=?", [(i,) for i in ids])
    conn.executemany("DELETE FROM seats WHERE showing_id=?", [(i,) for i in ids])
    conn.executemany("DELETE FROM showings WHERE id=?", [(i,) for i in ids])
    conn.commit()
    return len(ids)


def upsert_showing(conn: sqlite3.Connection, s: Showing) -> None:
    conn.execute(
        """INSERT INTO showings
             (id, theater, auditorium, film, fmt, start_time, checkout_url, screen_center_x, screen_y)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             start_time=excluded.start_time,
             fmt=excluded.fmt,
             auditorium=excluded.auditorium,
             checkout_url=excluded.checkout_url,
             screen_center_x=excluded.screen_center_x,
             screen_y=excluded.screen_y""",
        (s.id, s.theater, s.auditorium, s.film, s.fmt, s.start_time,
         s.checkout_url, s.screen_center_x, s.screen_y),
    )
    conn.commit()


def upsert_seats(conn: sqlite3.Connection, seats: Iterable[Seat]) -> None:
    conn.executemany(
        """INSERT INTO seats (showing_id, seat_id, section, row, num, x, y, seat_type)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(showing_id, seat_id) DO UPDATE SET
             section=excluded.section, x=excluded.x, y=excluded.y,
             seat_type=excluded.seat_type""",
        [(s.showing_id, s.seat_id, s.section, s.row, s.num, s.x, s.y, s.seat_type)
         for s in seats],
    )
    conn.commit()


def insert_availability(conn: sqlite3.Connection, seats: Iterable[Seat], captured_at: str) -> None:
    """Append one snapshot. captured_at is supplied by the caller (no clock here)."""
    conn.executemany(
        """INSERT OR IGNORE INTO availability (showing_id, seat_id, captured_at, status)
           VALUES (?,?,?,?)""",
        [(s.showing_id, s.seat_id, captured_at, s.status) for s in seats],
    )
    conn.commit()
