"""Query layer over seats.db — read showings/seats/availability WITHOUT scraping.

This is the "serve" side of the split: ingest (snapshot.py / report.py) writes the
DB; everything here only reads it, so queries are instant and safe to repeat. Seat
status comes from the LATEST availability snapshot per showing.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from adapters.base import Seat, SeatStatus, Showing

# All venues are Manhattan; start_time is stored as naive NY-local ISO 8601.
NY = ZoneInfo("America/New_York")


def now_ny() -> str:
    """Current NY-local time as a naive ISO string, comparable to start_time."""
    return datetime.now(NY).strftime("%Y-%m-%dT%H:%M:%S")


def seats_for(conn: sqlite3.Connection, showing_id: str) -> list[Seat]:
    latest = conn.execute(
        "SELECT MAX(captured_at) FROM availability WHERE showing_id=?", (showing_id,)
    ).fetchone()[0]
    status = {}
    if latest:
        for sid, st in conn.execute(
            "SELECT seat_id, status FROM availability WHERE showing_id=? AND captured_at=?",
            (showing_id, latest),
        ):
            status[sid] = st
    seats = []
    for sid, section, row, num, x, y, stype in conn.execute(
        "SELECT seat_id, section, row, num, x, y, seat_type FROM seats WHERE showing_id=?",
        (showing_id,),
    ):
        seats.append(Seat(showing_id=showing_id, seat_id=sid, section=section, row=row,
                          num=num, x=x, y=y, seat_type=stype,
                          status=status.get(sid, SeatStatus.UNKNOWN)))
    return seats


def rows_for(conn: sqlite3.Connection, film: str, dates: list[str] | None = None,
             venues: list[str] | None = None, formats: list[str] | None = None,
             since: str | None = None) -> list[tuple]:
    """Return [(Showing, [Seat])] for the filters, straight from the DB.

    since: hide showings starting before this naive NY-local ISO time (None = all).
    """
    q = "SELECT id,theater,auditorium,film,fmt,start_time,checkout_url,screen_center_x,screen_y " \
        "FROM showings WHERE film=? AND id LIKE 'amc:%'"  # AMC = the rankable seats
    params: list = [film]
    if since:
        q += " AND start_time >= ?"
        params.append(since)
    if dates:
        q += " AND substr(start_time,1,10) IN (%s)" % ",".join("?" * len(dates))
        params += dates
    if formats:
        q += " AND fmt IN (%s)" % ",".join("?" * len(formats))
        params += formats
    if venues:  # match on theater name substring
        q += " AND (" + " OR ".join(["theater LIKE ?"] * len(venues)) + ")"
        params += [f"%{v}%" for v in venues]
    q += " ORDER BY start_time"
    out = []
    for r in conn.execute(q, params).fetchall():
        sh = Showing(id=r[0], theater=r[1], auditorium=r[2], film=r[3], fmt=r[4],
                     start_time=r[5], checkout_url=r[6], screen_center_x=r[7], screen_y=r[8])
        out.append((sh, seats_for(conn, sh.id)))
    return out


def regal_showings(conn: sqlite3.Connection, film: str,
                   dates: list[str] | None = None,
                   since: str | None = None) -> list[dict]:
    """Regal showings (deep-links, no seats) from the DB, for the Regal section."""
    q = ("SELECT id,theater,auditorium,fmt,start_time,checkout_url FROM showings "
         "WHERE film=? AND id LIKE 'regal:%'")
    params: list = [film]
    if since:
        q += " AND start_time >= ?"
        params.append(since)
    if dates:
        q += " AND substr(start_time,1,10) IN (%s)" % ",".join("?" * len(dates))
        params += dates
    q += " ORDER BY start_time"
    keys = ["id", "theater", "auditorium", "fmt", "start_time", "checkout_url"]
    return [dict(zip(keys, r)) for r in conn.execute(q, params).fetchall()]


# --- form option helpers ---------------------------------------------------
def films(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT DISTINCT film FROM showings ORDER BY film")]


def dates(conn, film: str, since: str | None = None) -> list[str]:
    """Distinct showing dates; with since, a day drops off once its last showing starts."""
    q = "SELECT DISTINCT substr(start_time,1,10) d FROM showings WHERE film=?"
    params: list = [film]
    if since:
        q += " AND start_time >= ?"
        params.append(since)
    return [r[0] for r in conn.execute(q + " ORDER BY d", params)]


def venues(conn, film: str) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT theater FROM showings WHERE film=? ORDER BY theater", (film,))]


def formats(conn, film: str) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT fmt FROM showings WHERE film=? ORDER BY fmt", (film,))]
