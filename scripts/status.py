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

    # Liveness must come from the FILE, not from captured_at. report.py stamps
    # captured_at once at pass start (report.py:60), so every row written during a
    # 25-minute pass carries the same timestamp — using it as a freshness signal
    # reports "stalled" the entire time the ingest is happily working. The WAL's
    # mtime is the actual "someone wrote to this DB just now".
    last = q("SELECT MAX(captured_at) FROM availability")[0][0]
    if last:
        print(f"\ncurrent pass started: {last}  (one captured_at per pass, not per fetch)")

    writes = [p.stat().st_mtime for p in (db.DEFAULT_DB, Path(f"{db.DEFAULT_DB}-wal"))
              if p.exists()]
    if writes:
        age = datetime.now().timestamp() - max(writes)
        state = "ingest is writing" if age < 120 else "idle — no pass running"
        print(f"last DB write: {age:.0f}s ago — {state}")
    conn.close()


if __name__ == "__main__":
    main()
