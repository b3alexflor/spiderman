"""Export live rows from seats.db -> samples/seed.json (the bundled demo dataset).

The inverse of seed_demo.py. A fresh clone has no scraped data, so `run.sh` seeds
the site from a committed snapshot to have something on screen in one second; that
snapshot has to be regenerated whenever the target film changes, or the demo shows
the wrong movie until the first live ingest lands.

    python scripts/ingest.py --once --days 1 --per-venue 3 --regal all   # get real data
    python scripts/export_seed.py                                       # freeze it

Only takes showings with seat maps (AMC) plus Regal deep-links (no seats by design).
SEED-marked rows are skipped so you can never re-freeze demo data into itself.

    python scripts/export_seed.py --max-amc 3 --out samples/seed.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db
import film as film_cfg
import query

OUT = Path(__file__).resolve().parent.parent / "samples" / "seed.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--film", default=film_cfg.FILM)
    ap.add_argument("--max-amc", type=int, default=3,
                    help="how many AMC showings (with seat maps) to freeze")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    conn = db.connect()
    rows = conn.execute(
        "SELECT id, theater, auditorium, film, fmt, start_time, checkout_url,"
        "       screen_center_x, screen_y"
        "  FROM showings WHERE film = ? AND id NOT LIKE '%SEED%'"
        "  ORDER BY start_time", (args.film,)).fetchall()
    if not rows:
        raise SystemExit(f"no live {args.film!r} showings in seats.db — run an ingest first")

    cols = ("id", "theater", "auditorium", "film", "fmt", "start_time",
            "checkout_url", "screen_center_x", "screen_y")
    amc, regal, captured = [], [], None
    for r in rows:
        sh = dict(zip(cols, r))
        if sh["id"].startswith("regal:"):
            regal.append(sh)
            continue
        if len(amc) >= args.max_amc:
            continue
        seats = query.seats_for(conn, sh["id"])
        if not seats:
            continue  # discovery-only row (seat map was blocked/unfetched)
        amc.append({"showing": sh, "seats": [asdict(s) for s in seats]})
        captured = captured or sh["start_time"]

    if not amc:
        raise SystemExit("found showings but none had seat maps — ingest seat data first")

    # captured_at anchors seed_demo.py's re-dating: it shifts every showing forward
    # by (today - this day), so the demo always reads as today.
    day = min(s["showing"]["start_time"] for s in amc)[:10]
    payload = {"amc": amc, "regal": regal, "captured_at": f"{day}T20:00:00"}

    out = Path(args.out)
    out.write_text(json.dumps(payload, indent=1))
    n_seats = sum(len(s["seats"]) for s in amc)
    print(f"[export] {out.relative_to(Path.cwd()) if out.is_absolute() else out}: "
          f"{len(amc)} AMC showings ({n_seats} seats), {len(regal)} Regal deep-links, "
          f"anchored {day}")
    conn.close()


if __name__ == "__main__":
    main()
