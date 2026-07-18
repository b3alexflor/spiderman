"""Render a captured showing's seat map as a self-contained HTML visualization.

Input: a JSON capture {showing, seats:[Seat dicts]} (see how report/fetch produce
Seat dicts). Output: an HTML file (page content — no <html>/<head>/<body> wrapper,
so it also publishes directly as an Artifact). The seat grid, heatmap, and legend
are fully server-rendered (CSS color-mix does the theme-aware heatmap), so it needs
no JavaScript.

    python scripts/report_html.py <capture.json> <out.html>
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze
from adapters.base import FORMAT_WEIGHT, Seat, SeatStatus, SeatType

_FMT_LABEL = {
    "IMAX_70MM": "IMAX · 70mm film", "DOLBY": "Dolby Cinema",
    "IMAX_LASER": "IMAX with Laser", "IMAX_DIGITAL": "IMAX", "PRIME": "Prime",
    "STANDARD": "Standard",
}


def _seats_from(cap: dict) -> list[Seat]:
    return [Seat(**s) for s in cap["seats"]]


def build_html(cap: dict) -> str:
    sh = cap["showing"]
    seats = _seats_from(cap)
    xs = [s.x for s in seats]
    ys = [s.y for s in seats]
    cols, rows = int(max(xs)), int(max(ys))

    # Geometry score for EVERY displayable seat (position quality), over the whole
    # auditorium extent — this is what the heatmap shades.
    geo = {s.seat_id: analyze._geometry_score(s, xs, ys, None) for s in seats}

    # Ranking of AVAILABLE seats (geometry x format x type) -> rank badges + list.
    ranked = analyze.rank(seats, sh["fmt"], top=None)
    rank_of = {s.seat_id: i + 1 for i, (s, _) in enumerate(ranked)}
    n_avail = sum(1 for s in seats if s.status == SeatStatus.AVAILABLE)
    fmt_label = _FMT_LABEL.get(sh["fmt"], sh["fmt"])

    # --- seat grid (server-rendered) ---
    cells = []
    for s in seats:
        classes = ["seat", s.status]
        if s.seat_type == SeatType.ACCESSIBLE:
            classes.append("accessible")
        elif s.seat_type == SeatType.COMPANION:
            classes.append("companion")
        r = rank_of.get(s.seat_id)
        is_best = s.status == SeatStatus.AVAILABLE and r is not None and r <= 5
        if is_best:
            classes.append("best")
        tip = f"{s.seat_id} · row {s.row} seat {s.num} · {s.status}"
        if s.status == SeatStatus.AVAILABLE:
            tip += f" · position {geo[s.seat_id]*100:.0f}/100"
        badge = f'<span class="rank">{r}</span>' if is_best else ""
        cells.append(
            f'<div class="{" ".join(classes)}" '
            f'style="grid-column:{int(s.x)};grid-row:{int(s.y)};--t:{geo[s.seat_id]:.3f}" '
            f'title="{html.escape(tip)}">{badge}</div>'
        )
    grid = "\n".join(cells)

    # --- ranked list (top 8 available, excluding accessible/companion) ---
    rows_html = []
    for i, (s, score) in enumerate(ranked[:8], 1):
        rows_html.append(
            f'<li><span class="li-rank">{i}</span>'
            f'<span class="li-seat">{html.escape(s.seat_id)}</span>'
            f'<span class="li-meta">row {html.escape(str(s.row))} · col {int(s.x)}</span>'
            f'<span class="li-score">{score:.3f}</span></li>'
        )
    ranked_list = "\n".join(rows_html) or '<li class="empty">No general-admission seats available.</li>'

    best = ranked[0] if ranked else None
    best_line = (f"{best[0].seat_id} — row {best[0].row}, "
                 f"{'center' if abs(best[0].x-(cols+1)/2) < cols*0.15 else 'off-center'}, "
                 f"score {best[1]:.3f}") if best else "— sold out —"

    when = sh["start_time"].replace("T", " ")
    captured = cap.get("captured_at", "")

    return _TEMPLATE.format(
        film=html.escape(sh["film"]), theater=html.escape(sh["theater"]),
        fmt=html.escape(fmt_label), when=html.escape(when),
        n_avail=n_avail, n_total=len(seats), cols=cols, rows=rows,
        pct=round(100 * n_avail / len(seats)) if seats else 0,
        best_line=html.escape(best_line), grid=grid, ranked_list=ranked_list,
        captured=html.escape(captured),
    )


_TEMPLATE = """<style>
:root{{
  --bg:#0d0e13; --panel:#15171f; --panel-2:#1b1e28; --ink:#ece8df; --ink-dim:#9c968a;
  --line:#282b36; --accent:#f0b429; --accent-bright:#ffcf5c;
  --heat-lo:#232a40; --heat-hi:#ffcf5c;               /* poor position -> optimal */
  --taken:#39303a; --accessible:#4fd1c5;
  --shadow:0 1px 0 rgba(255,255,255,.03), 0 8px 30px rgba(0,0,0,.5);
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,"Book Antiqua",Georgia,serif;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --mono:ui-monospace,"SF Mono","Cascadia Code",Menlo,Consolas,monospace;
}}
@media (prefers-color-scheme: light){{
  :root{{
    --bg:#e9ecf1; --panel:#f6f7f9; --panel-2:#eef0f4; --ink:#1b1d26; --ink-dim:#5f6472;
    --line:#d3d7e0; --accent:#c07c00; --accent-bright:#d98a04;
    --heat-lo:#cfd6e2; --heat-hi:#e0930a; --taken:#c9c2c9; --accessible:#0d9488;
    --shadow:0 1px 0 rgba(255,255,255,.6), 0 10px 28px rgba(30,40,70,.12);
  }}
}}
:root[data-theme="dark"]{{
  --bg:#0d0e13; --panel:#15171f; --panel-2:#1b1e28; --ink:#ece8df; --ink-dim:#9c968a;
  --line:#282b36; --accent:#f0b429; --accent-bright:#ffcf5c;
  --heat-lo:#232a40; --heat-hi:#ffcf5c; --taken:#39303a; --accessible:#4fd1c5;
}}
:root[data-theme="light"]{{
  --bg:#e9ecf1; --panel:#f6f7f9; --panel-2:#eef0f4; --ink:#1b1d26; --ink-dim:#5f6472;
  --line:#d3d7e0; --accent:#c07c00; --accent-bright:#d98a04;
  --heat-lo:#cfd6e2; --heat-hi:#e0930a; --taken:#c9c2c9; --accessible:#0d9488;
}}
*{{box-sizing:border-box}}
.wrap{{max-width:1080px;margin:0 auto;padding:clamp(20px,4vw,48px);
  background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.5;
  font-synthesis:none;-webkit-font-smoothing:antialiased}}
.eyebrow{{font-family:var(--mono);font-size:.72rem;letter-spacing:.22em;text-transform:uppercase;
  color:var(--accent);margin:0 0 .6rem}}
h1{{font-family:var(--serif);font-weight:600;font-size:clamp(2rem,5vw,3.1rem);line-height:1.02;
  margin:0 0 .5rem;text-wrap:balance;letter-spacing:.005em}}
h1 em{{font-style:italic;color:var(--accent-bright)}}
.sub{{color:var(--ink-dim);margin:0 0 1.4rem;font-size:1.02rem}}
.chips{{display:flex;flex-wrap:wrap;gap:.5rem;margin-bottom:1.8rem}}
.chip{{font-family:var(--mono);font-size:.8rem;padding:.4rem .7rem;border:1px solid var(--line);
  border-radius:999px;background:var(--panel);color:var(--ink);white-space:nowrap}}
.chip b{{color:var(--accent-bright);font-weight:600}}
.layout{{display:grid;grid-template-columns:1fr;gap:1.6rem}}
@media(min-width:820px){{.layout{{grid-template-columns:minmax(0,1fr) 260px}}}}
.stage{{background:var(--panel);border:1px solid var(--line);border-radius:16px;
  padding:clamp(16px,3vw,28px);box-shadow:var(--shadow);min-width:0}}
.screen{{height:34px;border-radius:6px 6px 30px 30px/6px 6px 18px 18px;margin:0 auto 26px;
  width:min(88%,620px);
  background:linear-gradient(180deg,var(--accent-bright),color-mix(in oklab,var(--accent) 40%,transparent));
  box-shadow:0 16px 46px -6px color-mix(in oklab,var(--accent-bright) 55%,transparent);
  display:flex;align-items:center;justify-content:center;
  font-family:var(--mono);font-size:.66rem;letter-spacing:.35em;text-transform:uppercase;
  color:#141008;font-weight:700}}
.mapscroll{{overflow-x:auto;padding-bottom:6px}}
.seatmap{{display:grid;grid-template-columns:repeat({cols},var(--cell,20px));
  grid-auto-rows:var(--cell,20px);gap:3px;justify-content:center;min-width:max-content;margin:0 auto}}
.seat{{border-radius:4px;position:relative;background:var(--taken);
  border:1px solid transparent}}
.seat.available{{
  background:color-mix(in oklab,var(--heat-hi) calc(var(--t)*100%),var(--heat-lo));}}
.seat.accessible{{outline:1.5px solid var(--accessible);outline-offset:-1px}}
.seat.companion{{outline:1.5px dotted var(--accessible);outline-offset:-1px}}
.seat.best{{box-shadow:0 0 0 2px var(--bg),0 0 0 3.5px var(--accent-bright),
  0 0 14px color-mix(in oklab,var(--accent-bright) 70%,transparent);z-index:2}}
.rank{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  font-family:var(--mono);font-size:.62rem;font-weight:700;color:#140f04}}
.legend{{display:flex;flex-wrap:wrap;gap:1.1rem;align-items:center;margin-top:22px;
  padding-top:16px;border-top:1px solid var(--line);font-size:.8rem;color:var(--ink-dim)}}
.grad{{width:120px;height:10px;border-radius:5px;
  background:linear-gradient(90deg,var(--heat-lo),var(--heat-hi))}}
.legend .sw{{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-1px;margin-right:5px}}
.k{{display:inline-flex;align-items:center;gap:.4rem}}
aside{{min-width:0}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:16px;
  padding:20px 20px 22px;box-shadow:var(--shadow)}}
.panel h2{{font-family:var(--mono);font-size:.72rem;letter-spacing:.16em;text-transform:uppercase;
  color:var(--ink-dim);margin:0 0 .3rem;font-weight:600}}
.pick{{font-family:var(--serif);font-size:1.35rem;color:var(--accent-bright);margin:.1rem 0 1rem;
  font-weight:600}}
ol.ranked{{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:.15rem}}
ol.ranked li{{display:grid;grid-template-columns:1.4rem 2.6rem 1fr auto;align-items:baseline;
  gap:.5rem;padding:.42rem .1rem;border-bottom:1px solid var(--line);font-size:.9rem}}
ol.ranked li:last-child{{border-bottom:none}}
.li-rank{{font-family:var(--mono);color:var(--accent);font-size:.78rem}}
.li-seat{{font-family:var(--mono);font-weight:700}}
.li-meta{{color:var(--ink-dim);font-size:.82rem}}
.li-score{{font-family:var(--mono);font-variant-numeric:tabular-nums;color:var(--ink-dim)}}
.li-rank:first-child{{}}
ol.ranked li:first-child .li-seat{{color:var(--accent-bright)}}
.empty{{color:var(--ink-dim);font-style:italic;display:block!important;border:none}}
footer{{margin-top:1.8rem;padding-top:1.1rem;border-top:1px solid var(--line);
  color:var(--ink-dim);font-size:.78rem;line-height:1.6}}
footer code{{font-family:var(--mono);color:var(--ink)}}
</style>

<main class="wrap">
  <p class="eyebrow">Best-seat finder · personal use</p>
  <h1><em>{film}</em> — where to sit</h1>
  <p class="sub">{theater} · {fmt} · {when}</p>
  <div class="chips">
    <span class="chip"><b>{n_avail}</b> of {n_total} seats open ({pct}%)</span>
    <span class="chip">Auditorium <b>{cols}&times;{rows}</b></span>
    <span class="chip">Screen at top · row&nbsp;1 nearest</span>
  </div>

  <div class="layout">
    <section class="stage">
      <div class="screen">Screen</div>
      <div class="mapscroll"><div class="seatmap">{grid}</div></div>
      <div class="legend">
        <span class="k">Poor <span class="grad"></span> Ideal</span>
        <span class="k"><span class="sw" style="background:var(--taken)"></span>Taken</span>
        <span class="k"><span class="sw" style="outline:1.5px solid var(--accessible);background:transparent"></span>Accessible</span>
        <span class="k"><span class="sw" style="box-shadow:0 0 0 2px var(--accent-bright)"></span>Top&nbsp;5 pick</span>
      </div>
    </section>

    <aside>
      <div class="panel">
        <h2>Best available</h2>
        <div class="pick">{best_line}</div>
        <ol class="ranked">
          {ranked_list}
        </ol>
      </div>
    </aside>
  </div>

  <footer>
    Ranked by <b>seat geometry</b> (centered, ~⅔ back, front rows and extreme angles
    penalized) &times; format &times; seat type. Accessible/companion seats are
    excluded from the ranking. Snapshot captured <code>{captured}</code>; availability
    is a moment in time. Personal-use tool — not affiliated with AMC.
  </footer>
</main>
"""


# ===========================================================================
# Repertory-calendar landing page: masthead + day tabs + format/time filters +
# a per-day ticket-stub pick + a rule-lined venue schedule (seat maps on expand).
# ===========================================================================
from datetime import date as _rdate  # noqa: E402

_FMT_SHORT = {"IMAX_70MM": "70mm", "DOLBY": "Dolby", "IMAX_LASER": "IMAX Laser",
              "IMAX_DIGITAL": "IMAX", "PRIME": "Prime", "STANDARD": "Std"}


def _seatmap_cells(fmt: str, seats: list[Seat]):
    xs = [s.x for s in seats]
    ys = [s.y for s in seats]
    cols, rows = int(max(xs)), int(max(ys))
    geo = {s.seat_id: analyze._geometry_score(s, xs, ys, None) for s in seats}
    ranked = analyze.rank(seats, fmt, top=None)
    rank_of = {s.seat_id: i + 1 for i, (s, _) in enumerate(ranked)}
    cells = []
    for s in seats:
        cl = ["seat", s.status]
        if s.seat_type == SeatType.ACCESSIBLE:
            cl.append("accessible")
        elif s.seat_type == SeatType.COMPANION:
            cl.append("companion")
        r = rank_of.get(s.seat_id)
        if s.status == SeatStatus.AVAILABLE and r is not None and r <= 3:
            cl.append("best")
        cells.append(f'<i class="{" ".join(cl)}" style="grid-column:{int(s.x)};grid-row:{int(s.y)};'
                     f'--t:{geo[s.seat_id]:.3f}" title="{html.escape(s.seat_id)} · {s.status}"></i>')
    return cols, rows, "".join(cells), ranked


def _ampm(iso: str) -> str:
    hh, mm = int(iso[11:13]), iso[14:16]
    ap = "a" if hh < 12 else "p"
    return f"{hh % 12 or 12}:{mm}{ap}"


def _bucket(hh: int) -> str:
    if hh >= 21 or hh < 5:
        return "late"
    if hh >= 17:
        return "eve"
    return "mat"


def _bar(score: float) -> str:
    return f'<span class="bar"><i style="width:{max(6, score*100):.0f}%"></i></span>'


def _show_row(sh, seats: list[Seat]) -> tuple[str, tuple | None]:
    t = _ampm(sh.start_time)
    hh = int(sh.start_time[11:13])
    bucket = _bucket(hh)
    fmt_full = _FMT_LABEL.get(sh.fmt, sh.fmt)
    common = f'data-fmt="{sh.fmt}" data-bucket="{bucket}"'
    if not seats:
        row = (f'<div class="show off" {common}><span class="s-time">{t}</span>'
               f'<span class="s-fmt">{html.escape(fmt_full)}</span>'
               f'<span class="s-seat">—</span><span class="s-bar"></span>'
               f'<span class="s-avail">no data</span><span class="s-go"></span></div>')
        return row, None
    cols, rows, cells, ranked = _seatmap_cells(sh.fmt, seats)
    n_avail = sum(1 for s in seats if s.status == SeatStatus.AVAILABLE)
    if not ranked:
        row = (f'<div class="show sold" {common}><span class="s-time">{t}</span>'
               f'<span class="s-fmt">{html.escape(fmt_full)}</span>'
               f'<span class="s-seat">—</span><span class="s-bar"></span>'
               f'<span class="s-avail">sold out</span><span class="s-go"></span></div>')
        return row, None
    seat, score = ranked[0]
    book = html.escape(sh.checkout_url)
    row = (
        f'<details class="show" {common}><summary>'
        f'<span class="s-time">{t}</span>'
        f'<span class="s-fmt">{html.escape(fmt_full)}</span>'
        f'<span class="s-seat">{html.escape(seat.seat_id)}</span>'
        f'<span class="s-bar">{_bar(score)}</span>'
        f'<span class="s-avail">{n_avail} open</span>'
        f'<a class="s-go" href="{book}" target="_blank" rel="noopener">Book →</a>'
        f'</summary><div class="s-map"><div class="screen"></div>'
        f'<div class="mapwrap"><div class="seatmap" style="--cols:{cols}">{cells}</div></div></div></details>')
    return row, (score, seat, sh)


def _weekday(d: str) -> str:
    try:
        return _rdate.fromisoformat(d).strftime("%a %b %-d")
    except Exception:
        return d


def build_report_page(rows: list, regal_rows: list, meta: dict) -> str:
    # group by day -> theater, preserving sorted order
    by_day: dict = {}
    fmts_present: list = []
    for sh, seats in sorted(rows, key=lambda r: (r[0].start_time, r[0].theater)):
        d = sh.start_time[:10]
        by_day.setdefault(d, {}).setdefault(sh.theater, []).append((sh, seats))
        if sh.fmt not in fmts_present:
            fmts_present.append(sh.fmt)
    days = sorted(by_day)

    # format chips (fixed sensible order)
    order = ["IMAX_70MM", "DOLBY", "IMAX_LASER", "IMAX_DIGITAL", "PRIME", "STANDARD"]
    fmts_present.sort(key=lambda f: order.index(f) if f in order else 99)
    fchips = '<button class="chip fmt-chip on" data-fmt="ALL" aria-pressed="true">All</button>' + "".join(
        f'<button class="chip fmt-chip" data-fmt="{f}" aria-pressed="false">{html.escape(_FMT_SHORT.get(f, f))}</button>'
        for f in fmts_present)
    tchips = "".join(
        f'<button class="chip time-chip{" on" if b == "ALL" else ""}" data-bucket="{b}" '
        f'aria-pressed="{"true" if b == "ALL" else "false"}">{lbl}</button>'
        for b, lbl in [("ALL", "Any time"), ("mat", "Matinee"), ("eve", "Evening"), ("late", "Late")])

    daytabs = "".join(
        f'<button class="daytab" data-day="{d}" aria-selected="{"true" if i == 0 else "false"}" '
        f'role="tab">{html.escape(_weekday(d))}</button>' for i, d in enumerate(days))

    panels = []
    for i, d in enumerate(days):
        day_picks = []
        venue_blocks = []
        for theater, showings in by_day[d].items():
            rows_html = []
            for sh, seats in showings:
                r, best = _show_row(sh, seats)
                rows_html.append(r)
                if best:
                    day_picks.append(best)
            venue_blocks.append(
                f'<div class="venue-block"><h3 class="venue-rule">{html.escape(theater)}</h3>'
                f'<div class="sched-head"><span>Time</span><span>Format</span><span>Best</span>'
                f'<span>Position</span><span>Seats</span><span></span></div>'
                f'<div class="sched">{"".join(rows_html)}</div></div>')
        day_picks.sort(key=lambda x: x[0], reverse=True)
        if day_picks:
            score, seat, sh = day_picks[0]
            stub = (
                f'<div class="stub"><div class="stub-l">'
                f'<span class="stub-k">Pick of {html.escape(_weekday(d))}</span>'
                f'<span class="stub-seat">{html.escape(seat.seat_id)}</span>'
                f'<span class="stub-meta">{_ampm(sh.start_time)} · {html.escape(_FMT_LABEL.get(sh.fmt, sh.fmt))}'
                f' · {html.escape(sh.theater)}</span></div>'
                f'<div class="stub-r"><span class="stub-pos">{score*100:.0f}<small>/100</small></span>'
                f'<a class="stub-book" href="{html.escape(sh.checkout_url)}" target="_blank" rel="noopener">Get tickets</a>'
                f'</div></div>')
        else:
            stub = '<div class="stub empty">No bookable seats this day — every showing is sold out.</div>'
        panels.append(f'<section class="day-panel" data-day="{d}"{"" if i == 0 else " hidden"}>'
                      f'{stub}{"".join(venue_blocks)}'
                      f'<p class="nomatch" hidden>Nothing matches these filters.</p></section>')

    regal_html = ""
    if regal_rows:
        items = "".join(
            f'<a class="rlink" href="{html.escape(s.checkout_url)}" target="_blank" rel="noopener">'
            f'<span class="rt">{_ampm(s.start_time)} · {html.escape(s.start_time[5:10])}</span>'
            f'<span class="rf">{html.escape(_FMT_LABEL.get(s.fmt, s.fmt))} · {html.escape(s.auditorium)} · {html.escape(s.theater)}</span></a>'
            for s in sorted(regal_rows, key=lambda s: s.start_time))
        regal_html = ('<section class="regal"><h2>Regal — pick seats yourself</h2>'
                      '<p class="rnote">Regal gates seat data behind a CAPTCHA, so we don\'t rank it. '
                      'Showtimes below link straight to Regal\'s own seat picker.</p>'
                      f'<div class="rgrid">{items}</div></section>')

    empty = '' if rows else ('<p class="nomatch" style="padding:2rem 0">No showings in the '
                             'database for this query. Run ingest (snapshot.py / report.py) or '
                             'seed_demo.py, or widen the filters above.</p>')
    body = (
        f'<main class="paper"><header class="masthead">'
        f'<div class="mast-top"><span>Manhattan Repertory</span><span>{html.escape(meta.get("captured_at", ""))}</span></div>'
        f'<h1>The Odyssey</h1>'
        f'<p class="strap">{html.escape(meta["where"])} &middot; {html.escape(meta["date"])} &middot; 70mm · IMAX · Dolby</p>'
        f'</header>{meta.get("query_form", "")}{empty}'
        f'<nav class="controls"{"" if rows else " hidden"}><div class="daytabs" role="tablist">{daytabs}</div>'
        f'<div class="chiprow"><span class="chiplabel">Format</span>{fchips}</div>'
        f'<div class="chiprow"><span class="chiplabel">Time</span>{tchips}</div></nav>'
        f'{"".join(panels)}{regal_html}'
        f'<footer>Seats ranked by geometry (centered, ~⅔ back) × format × type; accessible &amp; '
        f'companion excluded. Expand a showtime for its seat map — dim → red marks worse → ideal '
        f'position; the best three glow. Snapshot as of masthead time; seats move fast. '
        f'Personal-use tool, unaffiliated with AMC or Regal.</footer></main>'
        f'<script>{_JS}</script>')
    return f"<style>{_CSS}</style>\n{body}"


_JS = """
const st={fmts:new Set(['ALL']),bucket:'ALL'};
function apply(){
  document.querySelectorAll('.day-panel:not([hidden])').forEach(p=>{
    let any=false;
    p.querySelectorAll('.show').forEach(r=>{
      const okF=st.fmts.has('ALL')||st.fmts.has(r.dataset.fmt);
      const okT=st.bucket==='ALL'||r.dataset.bucket===st.bucket;
      r.hidden=!(okF&&okT); if(!r.hidden)any=true;
    });
    p.querySelectorAll('.venue-block').forEach(v=>{
      v.hidden=![...v.querySelectorAll('.show')].some(r=>!r.hidden);
    });
    const nm=p.querySelector('.nomatch'); if(nm)nm.hidden=any;
  });
}
function sync(){
  document.querySelectorAll('.fmt-chip').forEach(c=>{
    const on=st.fmts.has(c.dataset.fmt); c.classList.toggle('on',on); c.setAttribute('aria-pressed',on);});
  document.querySelectorAll('.time-chip').forEach(c=>{
    const on=st.bucket===c.dataset.bucket; c.classList.toggle('on',on); c.setAttribute('aria-pressed',on);});
}
document.addEventListener('click',e=>{
  const dt=e.target.closest('.daytab');
  if(dt){document.querySelectorAll('.day-panel').forEach(p=>p.hidden=p.dataset.day!==dt.dataset.day);
    document.querySelectorAll('.daytab').forEach(b=>b.setAttribute('aria-selected',b===dt));apply();return;}
  const fc=e.target.closest('.fmt-chip');
  if(fc){const f=fc.dataset.fmt;
    if(f==='ALL'){st.fmts=new Set(['ALL']);}
    else{st.fmts.delete('ALL'); st.fmts.has(f)?st.fmts.delete(f):st.fmts.add(f); if(!st.fmts.size)st.fmts=new Set(['ALL']);}
    sync();apply();return;}
  const tc=e.target.closest('.time-chip');
  if(tc){st.bucket=tc.dataset.bucket;sync();apply();return;}
});
sync();apply();
"""


_CSS = """
:root{
 --paper:#efece3;--panel:#f7f5ef;--ink:#1a1712;--ink-2:#6b6558;--line:#d8d3c5;--rule:#1a1712;
 --spot:#d33321;--spot-deep:#a8251a;--heat-lo:#e6e1d3;--heat-hi:#d33321;--taken:#d5cfc0;--acc:#1f7a70;
 --grot:"Helvetica Neue",Helvetica,"Arial Narrow",Arial,sans-serif;
 --sans:system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
 --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;}
@media(prefers-color-scheme:dark){:root{
 --paper:#15130e;--panel:#1c1a14;--ink:#efe9dc;--ink-2:#9a9284;--line:#2d291f;--rule:#efe9dc;
 --spot:#e8503f;--spot-deep:#ff6a58;--heat-lo:#2a2620;--heat-hi:#e8503f;--taken:#231f18;--acc:#4fd1c4;}}
:root[data-theme="light"]{--paper:#efece3;--panel:#f7f5ef;--ink:#1a1712;--ink-2:#6b6558;--line:#d8d3c5;--rule:#1a1712;--spot:#d33321;--spot-deep:#a8251a;--heat-lo:#e6e1d3;--heat-hi:#d33321;--taken:#d5cfc0;--acc:#1f7a70;}
:root[data-theme="dark"]{--paper:#15130e;--panel:#1c1a14;--ink:#efe9dc;--ink-2:#9a9284;--line:#2d291f;--rule:#efe9dc;--spot:#e8503f;--spot-deep:#ff6a58;--heat-lo:#2a2620;--heat-hi:#e8503f;--taken:#231f18;--acc:#4fd1c4;}
*{box-sizing:border-box}
.paper{max-width:940px;margin:0 auto;padding:clamp(16px,3.5vw,44px);background:var(--paper);color:var(--ink);font-family:var(--sans);line-height:1.45}
/* masthead */
.mast-top{display:flex;justify-content:space-between;font-family:var(--mono);font-size:.68rem;
 letter-spacing:.18em;text-transform:uppercase;color:var(--ink-2);
 padding-bottom:.5rem;border-bottom:1px solid var(--rule)}
h1{font-family:var(--grot);font-weight:800;font-stretch:condensed;text-transform:uppercase;
 letter-spacing:-.02em;font-size:clamp(2.8rem,10vw,6rem);line-height:.9;margin:.5rem 0 .3rem}
.strap{font-family:var(--mono);font-size:.8rem;color:var(--ink-2);margin:0 0 .2rem;
 padding-bottom:1rem;border-bottom:3px solid var(--rule)}
/* controls */
.controls{position:sticky;top:0;background:var(--paper);z-index:5;padding:1rem 0;margin-bottom:.6rem;
 border-bottom:1px solid var(--line)}
.daytabs{display:flex;gap:0;flex-wrap:wrap;margin-bottom:.8rem}
.daytab{font-family:var(--grot);font-weight:700;text-transform:uppercase;letter-spacing:.04em;font-size:.82rem;
 background:none;border:1px solid var(--line);border-right:none;color:var(--ink-2);padding:.5rem .9rem;cursor:pointer}
.daytab:last-child{border-right:1px solid var(--line)}
.daytab[aria-selected="true"]{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.chiprow{display:flex;align-items:center;gap:.4rem;flex-wrap:wrap;margin-top:.5rem}
.chiplabel{font-family:var(--mono);font-size:.66rem;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-2);margin-right:.3rem}
.chip{font-family:var(--sans);font-size:.78rem;background:none;border:1px solid var(--line);color:var(--ink-2);
 padding:.3rem .7rem;border-radius:999px;cursor:pointer}
.chip.on{background:var(--spot);border-color:var(--spot);color:#fff}
/* ticket stub */
.stub{display:flex;align-items:stretch;border:1.5px solid var(--rule);margin:1.2rem 0 1.6rem;background:var(--panel)}
.stub-l{flex:1;padding:16px 20px;display:flex;flex-direction:column;gap:.2rem}
.stub-r{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:.5rem;
 padding:16px 22px;border-left:2px dashed var(--rule);position:relative}
.stub-k{font-family:var(--mono);font-size:.66rem;letter-spacing:.18em;text-transform:uppercase;color:var(--spot)}
.stub-seat{font-family:var(--grot);font-weight:800;font-size:clamp(2.4rem,7vw,3.6rem);line-height:.95;letter-spacing:-.02em}
.stub-meta{font-family:var(--mono);font-size:.82rem;color:var(--ink-2)}
.stub-pos{font-family:var(--grot);font-weight:800;font-size:1.8rem;color:var(--spot)}
.stub-pos small{font-size:.9rem;color:var(--ink-2);font-weight:400}
.stub-book{font-family:var(--sans);font-weight:700;font-size:.8rem;text-decoration:none;color:#fff;background:var(--spot);padding:.5rem 1rem;white-space:nowrap}
.stub-book:hover{background:var(--spot-deep)}
.stub.empty{padding:16px 20px;font-family:var(--mono);font-size:.85rem;color:var(--ink-2)}
/* schedule */
.venue-block{margin-bottom:1.6rem}
.venue-rule{font-family:var(--grot);font-weight:800;text-transform:uppercase;letter-spacing:.02em;font-size:1rem;
 margin:0 0 .3rem;padding-bottom:.35rem;border-bottom:2px solid var(--rule);display:flex;justify-content:space-between}
.sched-head,.show>summary,.show{display:grid;
 grid-template-columns:3.4rem 1fr 3.2rem minmax(60px,1fr) 4.2rem 3.4rem;gap:.7rem;align-items:center}
.sched-head{font-family:var(--mono);font-size:.62rem;letter-spacing:.12em;text-transform:uppercase;
 color:var(--ink-2);padding:.4rem 0}
.show{border-top:1px solid var(--line)}
.show>summary{padding:.55rem 0;cursor:pointer;list-style:none}
.show>summary::-webkit-details-marker{display:none}
.show>summary:hover{background:color-mix(in oklab,var(--spot) 6%,transparent)}
.s-time{font-family:var(--mono);font-weight:700;font-size:.92rem}
.s-fmt{font-size:.85rem;color:var(--ink-2)}
.s-seat{font-family:var(--mono);font-weight:700;color:var(--spot)}
.s-avail{font-family:var(--mono);font-size:.76rem;color:var(--ink-2)}
.s-go{font-family:var(--mono);font-size:.76rem;color:var(--spot);text-decoration:none;text-align:right}
.s-go:hover{color:var(--spot-deep)}
.show.sold,.show.off{color:var(--ink-2)}
.show.sold .s-avail{color:var(--spot-deep)}
.bar{display:block;height:8px;background:var(--taken);position:relative}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--heat-lo),var(--heat-hi))}
/* expanded seat map */
.s-map{padding:12px 0 16px}
.screen{height:4px;width:56%;margin:0 auto 12px;background:var(--spot);opacity:.5;border-radius:0 0 30px 30px/0 0 10px 10px}
.mapwrap{overflow-x:auto}
.seatmap{display:grid;grid-template-columns:repeat(var(--cols),8px);grid-auto-rows:8px;gap:2px;justify-content:center;min-width:max-content;margin:0 auto}
.seat{background:var(--taken)}
.seat.available{background:color-mix(in oklab,var(--heat-hi) calc(var(--t)*100%),var(--heat-lo))}
.seat.accessible{outline:1px solid var(--acc);outline-offset:-1px}
.seat.best{background:var(--spot);box-shadow:0 0 0 1px var(--paper),0 0 4px var(--spot)}
.nomatch{font-family:var(--mono);color:var(--ink-2);font-size:.85rem;padding:1rem 0}
/* regal */
.regal{margin-top:2rem;border-top:3px solid var(--rule);padding-top:1.2rem}
h2{font-family:var(--grot);font-weight:800;text-transform:uppercase;font-size:1.3rem;margin:0 0 .3rem}
.rnote{color:var(--ink-2);font-size:.84rem;margin:.2rem 0 1rem;max-width:62ch}
.rgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:0;border:1px solid var(--line)}
.rlink{display:flex;flex-direction:column;gap:.15rem;padding:11px 14px;text-decoration:none;color:var(--ink);
 border:1px solid var(--line);margin:-.5px}
.rlink:hover{background:color-mix(in oklab,var(--spot) 7%,transparent)}
.rt{font-family:var(--mono);font-weight:700;font-size:.86rem}
.rf{color:var(--ink-2);font-size:.76rem}
footer{margin-top:2rem;padding-top:1rem;border-top:1px solid var(--line);color:var(--ink-2);font-size:.76rem;line-height:1.6}
@media(max-width:620px){
 .sched-head{display:none}
 .show>summary,.show{grid-template-columns:3rem 1fr 3rem 3.4rem;gap:.5rem}
 .s-fmt{grid-column:2}.s-bar{display:none}.s-go{display:none}
 .stub{flex-direction:column}.stub-r{border-left:none;border-top:2px dashed var(--rule);flex-direction:row}
}
"""


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python scripts/report_html.py <capture.json> <out.html>")
        raise SystemExit(2)
    cap = json.load(open(sys.argv[1]))
    Path(sys.argv[2]).write_text(build_html(cap))
    print(f"wrote {sys.argv[2]}")
