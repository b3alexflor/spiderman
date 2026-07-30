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
import subprocess
import sys
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

    # Liveness is NOT derivable from the data or the file:
    #   - captured_at is stamped once at pass start (report.py:60), so every row from
    #     a 25-minute pass shares one timestamp — it reads "stalled" the whole time.
    #   - seats.db mtime is useless too: db.connect() runs executescript(SCHEMA) on
    #     EVERY connect, so this very script bumps it, and so does the API server,
    #     which reconnects per request while the site polls every 60s.
    # The only honest answer is whether an ingest process exists.
    last = q("SELECT MAX(captured_at) FROM availability")[0][0]
    if last:
        print(f"\nnewest pass started: {last}  (one captured_at per pass, not per fetch)")

    try:
        found = subprocess.run(["pgrep", "-f", "ingest.py"], capture_output=True,
                               text=True, timeout=5).stdout.split()
    except (OSError, subprocess.SubprocessError):
        found = None
    if found is None:
        print("ingest: could not check (pgrep unavailable)")
    elif found:
        print(f"ingest: RUNNING (pid {', '.join(found)}) — data still landing")
    else:
        print("ingest: not running — this is the complete dataset until you start a pass")
    conn.close()


if __name__ == "__main__":
    main()
