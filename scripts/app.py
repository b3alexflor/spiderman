"""Local query app — serves the repertory page from seats.db (no live scraping).

Ingest (snapshot.py / report.py / seed_demo.py) fills the DB; this reads it. Change
film / dates / venues / formats via the URL or the on-page query form; the format &
time chips filter client-side. Zero third-party deps (stdlib http.server).

    python scripts/app.py            # http://localhost:8000
    python scripts/app.py 8080
"""
from __future__ import annotations

import html
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db
import film as film_cfg
import query
import report_html


def _query_form(conn, film, sel_dates, sel_venues, sel_formats) -> str:
    all_films = query.films(conn) or [film]
    all_dates = query.dates(conn, film)
    all_venues = query.venues(conn, film)
    all_formats = query.formats(conn, film)

    fopts = "".join(f'<option value="{html.escape(f)}"{" selected" if f == film else ""}>{html.escape(f)}</option>'
                    for f in all_films)
    dchecks = "".join(
        f'<label><input type="checkbox" name="date" value="{d}"'
        f'{" checked" if (not sel_dates or d in sel_dates) else ""}> {d}</label>' for d in all_dates)
    vchecks = "".join(
        f'<label><input type="checkbox" name="venue" value="{html.escape(v)}"'
        f'{" checked" if (not sel_venues or v in sel_venues) else ""}> {html.escape(v)}</label>'
        for v in all_venues)
    fmtchecks = "".join(
        f'<label><input type="checkbox" name="format" value="{f}"'
        f'{" checked" if (not sel_formats or f in sel_formats) else ""}> {html.escape(f)}</label>'
        for f in all_formats)

    return (
        '<form class="qform" method="get" action="/">'
        f'<div class="qf"><span class="qk">Film</span><select name="film" onchange="this.form.submit()">{fopts}</select></div>'
        f'<div class="qf"><span class="qk">Dates</span><div class="qopts">{dchecks or "—"}</div></div>'
        f'<div class="qf"><span class="qk">Venues</span><div class="qopts">{vchecks or "—"}</div></div>'
        f'<div class="qf"><span class="qk">Formats</span><div class="qopts">{fmtchecks or "—"}</div></div>'
        '<button class="qgo" type="submit">Query</button></form>'
        '<style>'
        '.qform{display:flex;flex-wrap:wrap;gap:1rem;align-items:flex-start;padding:1rem 0;margin-bottom:.4rem;'
        'border-bottom:1px solid var(--line)}'
        '.qf{display:flex;flex-direction:column;gap:.35rem}'
        '.qk{font-family:var(--mono);font-size:.64rem;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-2)}'
        '.qopts{display:flex;flex-direction:column;gap:.15rem;font-size:.82rem;max-height:8rem;overflow:auto}'
        '.qform label{display:flex;gap:.35rem;align-items:center;white-space:nowrap}'
        '.qform select{font:inherit;padding:.3rem;background:var(--panel);color:var(--ink);border:1px solid var(--line)}'
        '.qgo{align-self:flex-end;font-family:var(--sans);font-weight:700;background:var(--ink);color:var(--paper);'
        'border:none;padding:.5rem 1.1rem;cursor:pointer}'
        '</style>')


def _render(qs) -> bytes:
    conn = db.connect()
    film = qs.get("film", [film_cfg.FILM])[0]
    sel_dates = qs.get("date")
    sel_venues = qs.get("venue")
    sel_formats = qs.get("format")

    rows = query.rows_for(conn, film, sel_dates, sel_venues, sel_formats)
    form = _query_form(conn, film, sel_dates, sel_venues, sel_formats)

    span = "—"
    if rows:
        ds = sorted({sh.start_time[:10] for sh, _ in rows})
        span = ds[0] if len(ds) == 1 else f"{ds[0]} → {ds[-1]}"
    where = ", ".join(sorted({sh.theater for sh, _ in rows})) or "no venues"
    meta = {"where": where, "date": span, "captured_at": "from seats.db", "query_form": form}
    page = report_html.build_report_page(rows, [], meta)
    conn.close()
    return page.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        try:
            body = _render(parse_qs(u.query))
        except Exception as e:  # surface errors instead of a blank 500
            body = f"<pre>query error: {html.escape(str(e))}</pre>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass  # quiet


if __name__ == "__main__":
    port = int(next((a for a in sys.argv[1:] if a.isdigit()), "8000"))
    print(f"[app] querying seats.db — open http://localhost:{port}  (Ctrl-C to stop)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
