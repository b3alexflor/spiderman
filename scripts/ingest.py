"""Scheduled ingest daemon — periodically scrape → seats.db.

Runs as its OWN process, separate from the API (which only reads). WAL mode lets
them run together with no locking, and the API reconnects per request so it serves
fresh data the moment a pass finishes — no restart. Each pass appends an
availability snapshot, so history accrues (the revenue-forecaster time-series).

    python scripts/ingest.py --once                                  # one pass, now
    python scripts/ingest.py --interval 1800 --all-amc --days 3 --per-venue 4 --regal all
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import report
import venues as venues_mod
from adapters.regal import VENUES as REGAL_VENUES


def _resolve_venues(all_amc: bool, venue: str) -> list[dict]:
    if all_amc:
        return venues_mod.for_chain("amc", first_run_only=True)
    slugs = {s.strip() for s in venue.split(",") if s.strip()}
    by_slug = {v["slug"]: v for v in venues_mod.VENUES if v.get("slug")}
    return [by_slug.get(s, {"name": f"AMC ({s})", "slug": s}) for s in slugs]


def one_pass(args) -> None:
    venues = _resolve_venues(args.all_amc, args.venue)
    formats = {f.strip() for f in args.format.split(",") if f.strip()}
    regal = None
    if args.regal:
        regal = list(REGAL_VENUES) if args.regal == "all" else [c.strip() for c in args.regal.split(",")]
    date = args.date or _date.today().isoformat()
    print(f"[ingest] pass start — {len(venues)} venue(s), {args.days}d from {date}, "
          f"formats={sorted(formats)}, regal={bool(regal)}", flush=True)
    # persist=True writes showings + seats + an availability snapshot (and Regal
    # deep-links) to seats.db. We discard the text report. skip_fresh_min keeps a
    # staged launch (fast pass, then deep pass) from refetching the same seat maps.
    report.build(venues, args.film, date, formats, None, top=5, limit=args.limit,
                 persist=True, regal_codes=regal, html_path=None,
                 per_venue=args.per_venue, days=args.days, skip_fresh_min=10)
    print("[ingest] pass done", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--film", default="The Odyssey")
    ap.add_argument("--date", default=None, help="start date (default: today)")
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--format", default="IMAX_70MM,DOLBY,IMAX_LASER,PRIME,STANDARD")
    ap.add_argument("--venue", default="amc-lincoln-square-13")
    ap.add_argument("--all-amc", action="store_true")
    ap.add_argument("--per-venue", type=int, default=4)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--regal", nargs="?", const="all", default=None)
    ap.add_argument("--once", action="store_true", help="one pass then exit")
    ap.add_argument("--interval", type=int, default=1800, help="seconds between passes")
    args = ap.parse_args()

    while True:
        try:
            one_pass(args)
        except Exception as e:  # keep the daemon alive across transient failures
            print(f"[ingest] pass error: {e}", flush=True)
        if args.once:
            break
        print(f"[ingest] sleeping {args.interval}s…", flush=True)
        time.sleep(args.interval)
