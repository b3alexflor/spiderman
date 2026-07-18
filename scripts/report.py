"""Best-available-seat report for today's Odyssey showings at AMC Lincoln Square.

Discovers showings, fetches each seat map, ranks available seats by geometry +
format/section, and prints (optionally saves) a report + the single overall best
seat. Persists seats + an availability snapshot to SQLite unless --no-db.

Politeness: defaults to --format IMAX_70MM so a default run only fetches the trophy
showings (each fetch is throttled to AMC's 8s floor). Widen deliberately.

    python scripts/report.py                                  # IMAX 70mm, all of them
    python scripts/report.py --format IMAX_70MM,DOLBY --top 8
    python scripts/report.py --format IMAX_LASER --section Regular --limit 3
    python scripts/report.py --no-db --limit 2                # quick, no persistence
"""
from __future__ import annotations

import argparse
import sys
from datetime import date as _date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze
import db
import rate
import venues as venues_mod
from browser import BrowserSession
from adapters.amc import AMCAdapter
from adapters.regal import RegalAdapter, VENUES as REGAL_VENUES
from adapters.base import SeatStatus

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


def build(venues: list[dict], film: str, date: str, formats: set[str], section: str | None,
          top: int, limit: int | None, persist: bool,
          include_accessible: bool = False, regal_codes: list[str] | None = None,
          html_path: str | None = None, per_venue: int | None = None, days: int = 1,
          skip_fresh_min: float | None = None) -> str:
    # ONE Chromium serves every request in the pass (rate.py still gates each
    # navigation); always torn down, even on an early return or a crash.
    session = BrowserSession()
    try:
        return _build(session, venues, film, date, formats, section, top, limit,
                      persist, include_accessible, regal_codes, html_path,
                      per_venue, days, skip_fresh_min)
    finally:
        session.close()


def _build(session: BrowserSession, venues: list[dict], film: str, date: str,
           formats: set[str], section: str | None, top: int, limit: int | None,
           persist: bool, include_accessible: bool, regal_codes: list[str] | None,
           html_path: str | None, per_venue: int | None, days: int,
           skip_fresh_min: float | None) -> str:
    conn = db.connect() if persist else None
    captured_at = datetime.now().isoformat(timespec="seconds")
    multi = len(venues) > 1
    report_rows: list = []   # (Showing, seats) for the HTML page
    regal_rows: list = []

    start = _date.fromisoformat(date)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(max(1, days))]

    # One shared throttle so each host's floor is enforced across ALL venues/chains.
    shared = rate.PoliteThrottle()
    # (adapter, showing) pairs, so each showing keeps its venue for fetch + display.
    pairs: list[tuple[AMCAdapter, object]] = []
    for v in venues:
        adapter = AMCAdapter(v, throttle=shared, session=session)
        for d in dates:
            for s in adapter.discover(film, d):
                if s.fmt in formats:
                    pairs.append((adapter, s))
    pairs.sort(key=lambda p: (p[1].start_time, p[1].theater))
    if persist and skip_fresh_min:
        # Don't re-fetch a seat map we snapshotted minutes ago (e.g. the fast
        # launch pass) — the polite budget goes to showings we DON'T have yet.
        cutoff = (datetime.now() - timedelta(minutes=skip_fresh_min)).isoformat(timespec="seconds")
        fresh = {r[0] for r in conn.execute(
            "SELECT DISTINCT showing_id FROM availability WHERE captured_at >= ?", (cutoff,))}
        skipped = sum(1 for _, s in pairs if s.id in fresh)
        if skipped:
            pairs = [(a, s) for a, s in pairs if s.id not in fresh]
            print(f"[report] {skipped} showing(s) snapshotted <{skip_fresh_min:g}m ago — not refetching")
    if per_venue:  # balanced coverage: soonest N per venue PER DAY
        seen: dict = {}
        capped = []
        for a, s in pairs:
            k = (s.theater, s.start_time[:10])
            seen[k] = seen.get(k, 0) + 1
            if seen[k] <= per_venue:
                capped.append((a, s))
        pairs = capped
    if limit:
        pairs = pairs[:limit]
    if not pairs:
        vlabel = "all AMC venues" if multi else venues[0]["name"]
        span = date if days == 1 else f"{dates[0]}..{dates[-1]}"
        return f"No {'/'.join(sorted(formats))} showings of {film!r} found for {span} at {vlabel}."

    print(f"[report] fetching seats for {len(pairs)} showing(s), throttled — "
          f"~{len(pairs) * 17}s...")

    lines: list[str] = []
    fmt_label = "/".join(sorted(formats))
    where = f"{len(venues)} Manhattan AMCs" if multi else venues[0]["name"]
    span_label = date if days == 1 else f"{dates[0]} → {dates[-1]}"
    lines.append(f"{film} — best available seats @ {where} — {span_label}")
    lines.append(f"Formats: {fmt_label}"
                 + (f" | Section: {section}" if section else "")
                 + f" | captured {captured_at}")
    lines.append("=" * 68)

    global_best = None  # (score, seat, showing)
    wrote_live = False  # any real seat data persisted this pass?
    for adapter, sh in pairs:
        seats = list(adapter.fetch_seats(sh))
        report_rows.append((sh, seats))   # full seats (pre-section-filter) for the viz
        if persist and seats:
            db.upsert_showing(conn, sh)
            db.upsert_seats(conn, seats)
            db.insert_availability(conn, seats, captured_at)
            if not wrote_live:
                # First live write of the pass: evict demo rows NOW so the site
                # never shows fake showings next to real ones. A fully failed
                # pass (Cloudflare, offline) still leaves the demo intact.
                pruned = db.prune_stale(conn)
                if pruned:
                    print(f"[report] live data in — pruned {pruned} demo/seed showing(s)")
            wrote_live = True
        if section:
            seats = [s for s in seats if s.section.lower() == section.lower()]
        ranked = analyze.rank(seats, sh.fmt, top=top, include_accessible=include_accessible)
        avail = sum(1 for s in seats if s.status == SeatStatus.AVAILABLE)

        t = sh.start_time[11:16]
        day_tag = (sh.start_time[5:10] + " ") if days > 1 else ""
        venue_tag = (sh.theater.replace("AMC ", "").replace(" 13", "").replace(" 25", "")[:14] + "  ") if multi else ""
        head = f"\n{day_tag}{t}  {venue_tag}{sh.auditorium:<22}"
        if not seats:
            lines.append(head + "  — ⚠ no seat data (fetch failed / not seatable)")
            continue
        if not ranked:
            note = "sold out" if avail == 0 else f"{avail} available but only reserved/accessible"
            lines.append(head + f"  — {note}")
            continue
        lines.append(head + f"  {avail} available")
        for i, (s, score) in enumerate(ranked, 1):
            lines.append(f"    {i}. {s.seat_id:5} row {s.row:<2} col {int(s.x):<2} "
                         f"score {score:.3f}  [{s.seat_type}]")
        best_here = ranked[0]
        if global_best is None or best_here[1] > global_best[0]:
            global_best = (best_here[1], best_here[0], sh)

    lines.append("\n" + "=" * 68)
    if global_best:
        score, seat, sh = global_best
        at = f"@ {sh.start_time[11:16]} {sh.auditorium}"
        if multi:
            at += f" — {sh.theater}"
        lines.append(f"★ OVERALL BEST: {seat.seat_id} (row {seat.row} col {int(seat.x)}) "
                     f"{at} — score {score:.3f}")
    else:
        lines.append("★ No available seats in any selected showing (all sold out).")

    # --- Regal: deep-links only (seats are CAPTCHA-gated; the human picks them) ---
    if regal_codes:
        lines.append("\n" + "=" * 68)
        lines.append("REGAL — pick seats yourself (Regal gates seat data behind a CAPTCHA):")
        for code in regal_codes:
            ra = RegalAdapter(code, throttle=shared, session=session)
            rshowings = []
            for d in dates:
                rshowings.extend(ra.discover(film, d))
            if not rshowings:
                continue
            regal_rows.extend(rshowings)
            if persist:  # store Regal deep-links too (no seats) so the API can serve them
                for s in rshowings:
                    db.upsert_showing(conn, s)
            lines.append(f"\n  {rshowings[0].theater}")
            for s in rshowings:
                dtag = (s.start_time[5:10] + " ") if days > 1 else ""
                lines.append(f"    {dtag}{s.start_time[11:16]}  {s.fmt:9} {s.auditorium:14}  {s.checkout_url}")

    if html_path:
        from report_html import build_report_page
        meta = {"film": film, "where": where, "date": span_label,
                "formats": fmt_label, "captured_at": captured_at, "multi": multi, "days": days}
        Path(html_path).parent.mkdir(parents=True, exist_ok=True)
        Path(html_path).write_text(build_report_page(report_rows, regal_rows, meta))
        lines.append(f"\n[report] HTML page -> {html_path}  (open in a browser)")

    if conn:
        conn.close()
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--film", default="The Odyssey")
    ap.add_argument("--date", default=None, help="start date YYYY-MM-DD (default: today)")
    ap.add_argument("--days", type=int, default=1, help="number of days to plan across (e.g. 3)")
    ap.add_argument("--format", default="IMAX_70MM",
                    help="comma-separated FORMAT_WEIGHT keys (default IMAX_70MM)")
    ap.add_argument("--section", default=None, help="filter by seat section/tier")
    ap.add_argument("--top", type=int, default=5, help="top seats per showing")
    ap.add_argument("--limit", type=int, default=None, help="cap total showings fetched")
    ap.add_argument("--per-venue", type=int, default=None,
                    help="cap showings fetched per venue (balanced coverage for --all-amc)")
    ap.add_argument("--venue", default="amc-lincoln-square-13",
                    help="comma-separated AMC venue slugs (default Lincoln Square)")
    ap.add_argument("--all-amc", action="store_true",
                    help="all first-run Manhattan AMCs from venues.py (many hits!)")
    ap.add_argument("--regal", nargs="?", const="all", default=None,
                    help="append Regal deep-links: 'all' or comma theatre codes (e.g. 1412,1335)")
    ap.add_argument("--no-db", action="store_true", help="don't persist to SQLite")
    ap.add_argument("--include-accessible", action="store_true",
                    help="include accessible/companion seats in the ranking")
    ap.add_argument("--save", action="store_true", help="also write text report to reports/")
    ap.add_argument("--html", nargs="?", const="", default=None,
                    help="render a self-contained HTML landing page (optional path)")
    args = ap.parse_args()
    args.date = args.date or _date.today().isoformat()

    if args.all_amc:
        venues = venues_mod.for_chain("amc", first_run_only=True)
    else:
        want = {s.strip() for s in args.venue.split(",") if s.strip()}
        by_slug = {v["slug"]: v for v in venues_mod.VENUES if v.get("slug")}
        venues = [by_slug.get(s, {"name": f"AMC ({s})", "slug": s}) for s in want]

    regal_codes = None
    if args.regal:
        regal_codes = (list(REGAL_VENUES) if args.regal == "all"
                       else [c.strip() for c in args.regal.split(",") if c.strip()])

    html_path = None
    if args.html is not None:
        html_path = args.html or str(REPORTS_DIR / f"report-{args.date}.html")

    formats = {f.strip() for f in args.format.split(",") if f.strip()}
    report = build(venues, args.film, args.date, formats, args.section,
                   args.top, args.limit, persist=not args.no_db,
                   include_accessible=args.include_accessible, regal_codes=regal_codes,
                   html_path=html_path, per_venue=args.per_venue, days=args.days)
    print("\n" + report)

    if args.save:
        REPORTS_DIR.mkdir(exist_ok=True)
        out = REPORTS_DIR / f"best-seats-{args.date}-{'_'.join(sorted(formats))}.txt"
        out.write_text(report)
        print(f"\n[report] saved -> {out}")
