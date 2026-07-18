"""Seed seats.db from the bundled sample dataset (samples/seed.json), so a fresh
clone can run the app with real-looking data WITHOUT scraping. This mirrors what
ingest does; it just loads a committed snapshot instead of hitting AMC.

The sample is RE-DATED on load: every showing shifts forward by (today - capture
day), keeping its time of day, so the demo always shows "today/tomorrow" instead
of going stale. Times are NY-local like everything else. Note the AMC/Regal
booking links still point at the original (long-expired) showtimes — the demo is
for the UI, not for buying tickets.

Demo rows are written with SEED-marked ids (amc:SEED-...), which is what
db.prune_stale() matches: the moment a real ingest lands live data, the demo
showings are deleted so fake and live rows never mix on the site.

    python scripts/seed_demo.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db
from adapters.base import Seat, Showing

SEED = Path(__file__).resolve().parent.parent / "samples" / "seed.json"
NY = ZoneInfo("America/New_York")


def _shift(iso: str, delta: timedelta) -> str:
    return (datetime.fromisoformat(iso) + delta).isoformat(timespec="seconds")


def _seed_id(real_id: str) -> str:
    """amc:143822255 -> amc:SEED-143822255 — keeps the chain prefix (the query
    layer filters on it) while matching prune_stale's '%SEED%' marker."""
    chain, _, rest = real_id.partition(":")
    return f"{chain}:SEED-{rest}"


def _redate_regal_url(url: str, new_start: str) -> str:
    """Regal deep-links carry the showing date as date=MM-DD-YYYY — keep it in sync."""
    d = datetime.fromisoformat(new_start).strftime("%m-%d-%Y")
    return re.sub(r"date=\d{2}-\d{2}-\d{4}", f"date={d}", url)


def main():
    if not SEED.exists():
        raise SystemExit(f"missing {SEED} — is this a full clone?")
    data = json.loads(SEED.read_text())

    base_day = datetime.fromisoformat(data.get("captured_at", "2026-07-17T20:00:00")).date()
    now = datetime.now(NY)
    delta = timedelta(days=(now.date() - base_day).days)
    captured_at = now.strftime("%Y-%m-%dT%H:%M:%S")  # snapshot = when we seeded
    if delta:
        print(f"[seed] re-dating sample +{delta.days}d (captured {base_day} -> today {now.date()})")

    conn = db.connect()
    # A DB that already holds LIVE rows doesn't need demo data — re-seeding would
    # put fake showings back next to real ones until the next ingest pass.
    live = conn.execute("SELECT COUNT(*) FROM showings WHERE id NOT LIKE '%SEED%'").fetchone()[0]
    if live:
        print(f"[seed] {live} live showing(s) already in seats.db — skipping demo seed")
        conn.close()
        return
    db.prune_stale(conn)
    n = 0
    for row in data.get("amc", []):
        row["showing"]["id"] = _seed_id(row["showing"]["id"])
        row["showing"]["start_time"] = _shift(row["showing"]["start_time"], delta)
        sh = Showing(**row["showing"])
        seats = [Seat(**{**s, "showing_id": sh.id}) for s in row["seats"]]
        db.upsert_showing(conn, sh)
        db.upsert_seats(conn, seats)
        db.insert_availability(conn, seats, captured_at)
        n += 1
        print(f"[seed] {sh.id}  {sh.start_time}  {sh.fmt}  {len(seats)} seats")
    for s in data.get("regal", []):  # Regal deep-links (no seats)
        s["id"] = _seed_id(s["id"])
        s["start_time"] = _shift(s["start_time"], delta)
        s["checkout_url"] = _redate_regal_url(s["checkout_url"], s["start_time"])
        db.upsert_showing(conn, Showing(**s))
        n += 1
    conn.close()
    print(f"[seed] wrote {n} showings to seats.db (incl Regal deep-links)")


if __name__ == "__main__":
    main()
