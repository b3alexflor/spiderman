"""Snapshot runner: for each adapter, discover -> fetch_seats -> DB + screenshot.

    python scripts/snapshot.py --film "The Odyssey" --date 2026-07-17 --at <ISO>

`--at` is the capture timestamp written to the availability time series. We pass it
in explicitly rather than reading a clock here, so runs are reproducible/testable.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402
from adapters.amc import AMCAdapter  # noqa: E402

ADAPTERS = [AMCAdapter()]  # add regal, indies as they're built


def run(film: str, date: str, captured_at: str) -> None:
    conn = db.connect()
    for adapter in ADAPTERS:
        showings = adapter.discover(film, date)
        print(f"[{adapter.name}] discovered {len(showings)} showing(s)")
        for sh in showings:
            db.upsert_showing(conn, sh)
            seats = adapter.fetch_seats(sh)
            if not seats:
                print(f"[{adapter.name}] no seats for {sh.id} (parser unwired / no url)")
                continue
            db.upsert_seats(conn, seats)
            db.insert_availability(conn, seats, captured_at)
            free = sum(1 for s in seats if s.status == "available")
            print(f"[{adapter.name}] {sh.id}: {free}/{len(seats)} available @ {captured_at}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--film", default="The Odyssey")
    ap.add_argument("--date", default="2026-07-17")
    ap.add_argument("--at", required=True, help="capture timestamp, ISO 8601")
    args = ap.parse_args()
    run(args.film, args.date, args.at)
