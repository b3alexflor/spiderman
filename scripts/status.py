"""Is the ingest actually getting data right now? Reads seats.db, not the log.

ingest.log is the usual answer to "how's it going", but the log is a side channel:
it can lag, buffer, or belong to a pass that already died. seats.db is the ground
truth, and WAL mode means we can read it while ingest is mid-write.

    python scripts/status.py
    watch -n 20 'python scripts/status.py'      # or just re-run it

Reads only — safe to run against a live ingest.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db
import film as film_cfg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--film", default=film_cfg.FILM)
    args = ap.parse_args()

    conn = db.connect()
    q = lambda sql, *a: conn.execute(sql, a).fetchall()  # noqa: E731

    n_show = q("SELECT COUNT(*) FROM showings WHERE film = ?", args.film)[0][0]
    n_mapped = q("SELECT COUNT(DISTINCT s.showing_id) FROM seats s"
                 " JOIN showings sh ON sh.id = s.showing_id WHERE sh.film = ?", args.film)[0][0]
    n_seats = q("SELECT COUNT(*) FROM seats")[0][0]
    n_snaps = q("SELECT COUNT(DISTINCT captured_at) FROM availability")[0][0]

    print(f"{args.film}")
    print(f"  {n_show} showings discovered · {n_mapped} with seat maps · "
          f"{n_seats} seats · {n_snaps} snapshots")

    print("\nby venue (mapped / discovered):")
    rows = q("SELECT sh.theater, COUNT(DISTINCT sh.id),"
             "       COUNT(DISTINCT CASE WHEN s.showing_id IS NOT NULL THEN sh.id END)"
             "  FROM showings sh LEFT JOIN seats s ON s.showing_id = sh.id"
             " WHERE sh.film = ? GROUP BY sh.theater ORDER BY 2 DESC", args.film)
    for theater, disc, mapped in rows:
        tag = "  (deep-links only, CAPTCHA-gated)" if theater.startswith("Regal") else ""
        print(f"  {mapped:3}/{disc:<4} {theater}{tag}")

    last = q("SELECT MAX(captured_at) FROM availability")[0][0]
    if last:
        try:
            age = (datetime.now() - datetime.fromisoformat(last)).total_seconds()
            moving = "ingest is writing" if age < 180 else "idle — pass finished or stalled"
            print(f"\nlast seat map: {last}  ({age/60:.1f} min ago — {moving})")
        except ValueError:
            print(f"\nlast seat map: {last}")
    conn.close()


if __name__ == "__main__":
    main()
