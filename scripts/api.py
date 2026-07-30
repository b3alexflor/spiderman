"""JSON API backend over seats.db (FastAPI). The website (web/index.html) and any
other client consume these endpoints; nothing here scrapes — it only reads the DB
that ingest (snapshot.py / report.py / seed_demo.py) populates.

    uvicorn api:app --app-dir scripts --reload      # http://127.0.0.1:8000
    #   docs at /docs   ·   site at /

Endpoints:
    GET /api/meta?film=...                  filter options (films, dates, venues, formats)
    GET /api/showings?film&date&venue&format  showing summaries + best seat
    GET /api/showings/{id}/seats            full seat map + per-seat geometry/rank
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze
import db
import film as film_cfg
import query
from adapters.base import FORMAT_WEIGHT, SeatStatus

WEB = Path(__file__).resolve().parent.parent / "web"
app = FastAPI(title="Manhattan Seat Finder", version="0.1",
              description=f"Query {film_cfg.FILM} seat availability + best-seat rankings from seats.db.")


@app.get("/api/meta")
def meta(film: str = film_cfg.FILM, include_past: bool = False):
    c = db.connect()
    try:
        since = None if include_past else query.now_ny()
        return {"films": query.films(c), "dates": query.dates(c, film, since),
                "venues": query.venues(c, film), "formats": query.formats(c, film),
                "format_weight": FORMAT_WEIGHT}
    finally:
        c.close()


@app.get("/api/showings")
def showings(film: str = film_cfg.FILM,
             date: list[str] | None = Query(None),
             venue: list[str] | None = Query(None),
             format: list[str] | None = Query(None),
             include_past: bool = False):
    """Showing summaries with availability + the single best seat (from the DB).

    Past showings are hidden unless include_past=true (availability history stays
    queryable — we filter, never delete).
    """
    c = db.connect()
    try:
        since = None if include_past else query.now_ny()
        out = []
        for sh, seats in query.rows_for(c, film, date, venue, format, since=since):
            avail = sum(1 for s in seats if s.status == SeatStatus.AVAILABLE)
            ranked = analyze.rank(seats, sh.fmt, top=1)
            best = ranked[0] if ranked else None
            out.append({
                "id": sh.id, "theater": sh.theater, "auditorium": sh.auditorium,
                "film": sh.film, "fmt": sh.fmt, "start_time": sh.start_time,
                "checkout_url": sh.checkout_url,
                "total": len(seats), "available": avail,
                "best_seat": best[0].seat_id if best else None,
                "best_score": round(best[1], 3) if best else None,
                "sold_out": avail == 0 if seats else None,
            })
        return out
    finally:
        c.close()


@app.get("/api/regal")
def regal(film: str = film_cfg.FILM, date: list[str] | None = Query(None),
          include_past: bool = False):
    """Regal showings — deep-links only (seats are CAPTCHA-gated; the human picks)."""
    c = db.connect()
    try:
        since = None if include_past else query.now_ny()
        return query.regal_showings(c, film, date, since=since)
    finally:
        c.close()


@app.get("/api/showings/{showing_id}/seats")
def seatmap(showing_id: str):
    """Full seat grid for one showing: coords, status, geometry score, rank."""
    c = db.connect()
    try:
        row = c.execute("SELECT fmt, theater, start_time FROM showings WHERE id=?",
                        (showing_id,)).fetchone()
        if not row:
            raise HTTPException(404, "unknown showing")
        seats = query.seats_for(c, showing_id)
        if not seats:
            raise HTTPException(404, "no seat data for this showing")
        xs = [s.x for s in seats]
        ys = [s.y for s in seats]
        geo = {s.seat_id: analyze._geometry_score(s, xs, ys, None) for s in seats}
        rank = {s.seat_id: i + 1 for i, (s, _) in enumerate(analyze.rank(seats, row[0], top=None))}
        return {
            "showing_id": showing_id, "fmt": row[0], "theater": row[1], "start_time": row[2],
            "cols": int(max(xs)), "rows": int(max(ys)),
            "seats": [{"seat_id": s.seat_id, "row": s.row, "num": s.num,
                       "x": s.x, "y": s.y, "type": s.seat_type, "status": s.status,
                       "geo": round(geo[s.seat_id], 3), "rank": rank.get(s.seat_id)}
                      for s in seats],
        }
    finally:
        c.close()


@app.get("/")
def index():
    idx = WEB / "index.html"
    if not idx.exists():
        return {"ok": True, "hint": "API up. Frontend missing; try /docs or /api/meta"}
    return FileResponse(idx)
