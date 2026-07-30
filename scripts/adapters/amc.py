"""AMC adapter — starts with AMC Lincoln Square 13 (70mm IMAX + Dolby Cinema).

discover() is WIRED: it loads the (server-rendered) showtimes page for a date,
harvests every /showtimes/<id> link with its surrounding text in one in-page pass,
and turns the ones for our film into Showings (real showtimeId, format, checkout
URL). All film/format/time decisions live in pure helpers below so they're
unit-testable without a browser.

fetch_seats() is WIRED: AMC embeds the full seat map as JSON (`seatingLayout`) in
the /showtimes/<id>/seats page's RSC payload — no XHR to intercept. We navigate
there, extract + parse it. Cloudflare occasionally challenges automated requests;
looks_blocked() detects that so we back off instead of mistaking it for empty.

    python scripts/adapters/amc.py --discover        # discover + print
    python scripts/adapters/amc.py --dump            # + save rendered showtimes HTML to recon/
    python scripts/adapters/amc.py --recon           # + fetch one showing's seats (saves HTML)
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date as _date
from pathlib import Path
from typing import Sequence

# Allow running this file directly (python scripts/adapters/amc.py ...)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import film as film_cfg
import rate
from browser import BrowserSession
from adapters.base import Seat, SeatStatus, SeatType, Showing

RECON_DIR = Path(__file__).resolve().parent.parent / "recon"
IMAGES_DIR = Path(__file__).resolve().parent.parent.parent / "images"

THEATER_NAME = "AMC Lincoln Square 13"
THEATER_SLUG = "amc-lincoln-square-13"
THEATER_CITY = "new-york-city"

# PINNED endpoints (confirmed 2026-07-17):
SHOWTIMES_URL = ("https://www.amctheatres.com/movie-theatres/"
                 f"{THEATER_CITY}/{THEATER_SLUG}/showtimes")  # + "?date=YYYY-MM-DD"
CHECKOUT_URL = "https://www.amctheatres.com/showtimes/{showtime_id}"
# Gated api.amctheatres.com needs X-AMC-Vendor-Key (not being issued) — scrape the
# public page above instead. theatreId only needed for that API (in __NEXT_DATA__).

# AMC encodes film + format in each showtime link's aria-describedby, e.g.
#   "the-odyssey-76238  the-odyssey-76238-amc-lincoln-square-13  ...-70mm  ..."
# The first token is <film-slug>-<releaseId>; format tokens appear later. We read
# that (authoritative) rather than climbing the DOM. Format tokens -> our keys;
# ORDER MATTERS (check "imax70mm" before generic "imax").
_FORMAT_TOKENS = (
    ("imax70mm", "IMAX_70MM"),
    ("70mm", "IMAX_70MM"),
    ("dolbycinema", "DOLBY"),
    ("laseratamc", "IMAX_LASER"),
    ("imax", "IMAX_DIGITAL"),
    ("prime", "PRIME"),
)

# AMC seat `type` -> our SeatType. "CanReserve" is a normal reservable seat.
_SEAT_TYPE_MAP = {
    "CanReserve": SeatType.STANDARD,
    "Companion": SeatType.COMPANION,
    "Wheelchair": SeatType.ACCESSIBLE,
    # "NotASeat" is filtered out via shouldDisplay.
}

_ID_RE = re.compile(r"/showtimes/(\d+)")
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*([AaPp][Mm])\b")
_RELEASE_SUFFIX_RE = re.compile(r"-\d+$")

# A normal desktop Chrome UA (headless Chrome's own UA + a "seat-scraper" tag both
# get flagged by Cloudflare). Low volume + backoff keep us polite, not evasive.
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")

# Markers of a Cloudflare block/challenge page (so we don't mistake it for empty).
_BLOCK_MARKERS = ("Access denied", "Cloudflare to restrict", "challenge-platform",
                  "Attention Required", "Click to reveal")


def looks_blocked(html: str, status: int | None) -> bool:
    if status == 403:
        return True
    head = html[:4000]
    return "seatingLayout" not in html and any(m in head for m in _BLOCK_MARKERS)


try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - tzdata missing
    _ET = None

# In-page harvester: for every /showtimes/<id> link, read its aria-describedby
# (film+format) and inner <time datetime> (exact UTC instant) + visible time text.
_HARVEST_JS = """() => {
  const out = [];
  for (const a of document.querySelectorAll("a[href*='/showtimes/']")) {
    const m = (a.getAttribute('href') || '').match(/showtimes\\/(\\d+)/);
    if (!m) continue;
    const t = a.querySelector('time');
    out.push({
      id: m[1],
      describedby: a.getAttribute('aria-describedby') || '',
      datetime: t ? (t.getAttribute('datetime') || '') : '',
      timeText: t ? (t.textContent || '').replace(/\\s+/g, ' ').trim() : '',
    });
  }
  return out;
}"""


# --- Pure helpers (no browser) ---------------------------------------------
def film_slug(name: str) -> str:
    """'The Odyssey' -> 'the-odyssey' (matches AMC's aria-describedby slug)."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def parse_describedby(describedby: str, theater_slug: str = THEATER_SLUG) -> tuple[str | None, str]:
    """(film_slug, format_key) from a link's aria-describedby. Default STANDARD."""
    tokens = (describedby or "").split()
    if not tokens:
        return None, "STANDARD"
    # First token is the bare "<film-slug>-<releaseId>"; be defensive if extra
    # segments got appended by cutting at the theatre slug, then strip the release.
    first = tokens[0].split(f"-{theater_slug}")[0]
    fslug = _RELEASE_SUFFIX_RE.sub("", first)
    joined = describedby.lower()
    for token, key in _FORMAT_TOKENS:
        if token in joined:
            return fslug, key
    return fslug, "STANDARD"


def parse_time_iso(text: str, date: str) -> str | None:
    """Extract the first 'H:MM AM/PM' from `text` -> 'YYYY-MM-DDTHH:MM:00'."""
    m = _TIME_RE.search(text or "")
    if not m:
        return None
    h, mn, ap = int(m.group(1)), int(m.group(2)), m.group(3).lower()
    if ap == "pm" and h != 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    return f"{date}T{h:02d}:{mn:02d}:00"


def start_time_local(datetime_utc: str, time_text: str, date: str) -> str:
    """Prefer the authoritative <time datetime> (UTC) converted to ET; fall back to
    the visible local time text; last resort midnight."""
    if datetime_utc and _ET:
        try:
            from datetime import datetime as _dt
            d = _dt.fromisoformat(datetime_utc.replace("Z", "+00:00")).astimezone(_ET)
            return d.strftime("%Y-%m-%dT%H:%M:%S")
        except Exception:
            pass
    return parse_time_iso(time_text, date) or f"{date}T00:00:00"


def showtime_id(href: str) -> str | None:
    m = _ID_RE.search(href or "")
    return m.group(1) if m else None


def extract_seating_layout(html: str) -> dict | None:
    """Pull the `seatingLayout` object from a /seats page's RSC payload.

    It's embedded as an escaped JSON string (\\" for quotes). We brace-match from
    the key, unescape, and json-parse. Returns {columns, rows, seats:[...]} or None.
    """
    i = html.find("seatingLayout")
    if i < 0:
        return None
    j = html.find("{", i)
    if j < 0:
        return None
    depth = 0
    for k in range(j, len(html)):
        c = html[k]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                raw = html[j:k + 1]
                unescaped = raw.replace("\\\\", "\\").replace('\\"', '"')
                try:
                    return json.loads(unescaped)
                except (json.JSONDecodeError, ValueError):
                    return None
    return None


def auditorium_for(fmt: str) -> str:
    return {
        "IMAX_70MM": "IMAX (70mm film)",
        "DOLBY": "Dolby Cinema",
        "IMAX_LASER": "IMAX with Laser",
        "IMAX_DIGITAL": "IMAX",
        "PRIME": "Prime at AMC",
    }.get(fmt, "Standard")


def slug_matches(fslug: str | None, target: str,
                 include_events: bool = film_cfg.MATCH_EVENT_LISTINGS) -> bool:
    """Does a harvested film slug refer to our film?

    AMC lists special screenings as separate films whose slug EXTENDS the base one
    ("spider-man-brand-new-day-dolby-opening-night-fan-event"). Those are genuine
    showings with real seat maps, so by default a base-slug prefix counts as a
    match; see film.MATCH_EVENT_LISTINGS for when to turn that off.
    """
    if not fslug:
        return False
    return fslug == target or (include_events and fslug.startswith(f"{target}-"))


def records_to_showings(records: list[dict], film: str, date: str,
                        theater_name: str = THEATER_NAME,
                        theater_slug: str = THEATER_SLUG,
                        include_events: bool = film_cfg.MATCH_EVENT_LISTINGS) -> list[Showing]:
    """Turn harvested link records into de-duped Showings for `film`. Pure/tested."""
    target = film_slug(film)
    out: dict[str, Showing] = {}
    for r in records:
        fslug, fmt = parse_describedby(r.get("describedby", ""), theater_slug)
        if not slug_matches(fslug, target, include_events):
            continue  # a different movie's showtime
        sid = r["id"]
        if sid in out:
            continue
        out[sid] = Showing(
            id=f"amc:{sid}",
            theater=theater_name,
            auditorium=auditorium_for(fmt),
            film=film,
            fmt=fmt,
            start_time=start_time_local(r.get("datetime", ""), r.get("timeText", ""), date),
            checkout_url=CHECKOUT_URL.format(showtime_id=sid),
        )
    return list(out.values())


# Default venue = AMC Lincoln Square 13 (keeps AMCAdapter() zero-arg backward-compat).
DEFAULT_VENUE = {"name": THEATER_NAME, "slug": THEATER_SLUG, "city": THEATER_CITY}


class AMCAdapter:
    name = "amc"

    def __init__(self, venue: dict | None = None,
                 throttle: rate.PoliteThrottle | None = None,
                 session: BrowserSession | None = None):
        # Share ONE throttle across venue-adapters so AMC's per-host floor is
        # enforced across all Manhattan AMCs, not per-instance. Same for the
        # browser session: one Chromium per pass, not per request.
        self.venue = venue or DEFAULT_VENUE
        self.throttle = throttle or rate.PoliteThrottle()
        self.session = session or BrowserSession(user_agent=_UA)

    @property
    def showtimes_url(self) -> str:
        v = self.venue
        return ("https://www.amctheatres.com/movie-theatres/"
                f"{v.get('city', THEATER_CITY)}/{v['slug']}/showtimes")

    def discover(self, film: str, date: str, *, dump: bool = False) -> Sequence[Showing]:
        """Load this venue's showtimes page for `date`, return `film`'s showings."""
        records = self._harvest(date, dump=dump)
        showings = records_to_showings(records, film, date,
                                       self.venue["name"], self.venue["slug"])
        print(f"[amc:{self.venue['slug']}] discover: {len(records)} showtime links, "
              f"{len(showings)} match {film!r}")
        return showings

    def list_films(self, date: str, *, dump: bool = False) -> list[tuple[str, int]]:
        """Every film slug playing this venue on `date`, with its showtime count.

        Repurposing tool: the engine matches films by AMC's own slug, so before
        pointing it at a new title you need the slug AMC actually publishes (it
        is not always the marketing title slugified). Descending by count.
        """
        counts: dict[str, int] = {}
        for r in self._harvest(date, dump=dump):
            fslug, _ = parse_describedby(r.get("describedby", ""), self.venue["slug"])
            if fslug:
                counts[fslug] = counts.get(fslug, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    def _harvest(self, date: str, *, dump: bool = False) -> list[dict]:
        """Load the showtimes page for `date` and return raw link records.

        Shared by discover() (filter to one film) and list_films() (what's on).
        """
        slug = self.venue["slug"]
        url = f"{self.showtimes_url}?date={date}"
        self.throttle.before_request(url)

        page = self.session.page()
        try:
            # networkidle never settles on AMC (persistent analytics), so wait for
            # DOM + the showtime links themselves, with a bounded fallback.
            resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            status = resp.status if resp else 0
            self.throttle.note_result(url, status)
            if status >= 400:
                print(f"[amc:{slug}] HTTP {status} — bad slug or unavailable, skipping")
                return []
            try:
                page.wait_for_selector("a[href*='/showtimes/']", timeout=15000)
            except Exception:
                print(f"[amc:{slug}] no /showtimes/ links (no showings for date, "
                      "wrong slug, or a block — check --dump)")
            page.wait_for_timeout(1500)  # let late showtime cards settle

            if dump:
                RECON_DIR.mkdir(exist_ok=True)
                (RECON_DIR / f"showtimes-{slug}-{date}.html").write_text(page.content())
                print(f"[amc] dump: rendered page -> {RECON_DIR}/showtimes-{slug}-{date}.html")

            records = page.evaluate(_HARVEST_JS)
        finally:
            page.close()
        return records

    def fetch_seats(self, showing: Showing, *, recon: bool = False) -> Sequence[Seat]:
        """Load the showing's /seats page and return its live seat map.

        AMC embeds the full seat layout as JSON in the /showtimes/<id>/seats page's
        RSC payload (no XHR to intercept). We navigate there, read the page HTML,
        extract `seatingLayout`, and map it to Seat[]. Always saves an archival
        screenshot; `recon` also dumps the raw HTML.
        """
        if not showing.checkout_url:
            print(f"[amc] no checkout_url for {showing.id}")
            return []

        IMAGES_DIR.mkdir(exist_ok=True)
        seats_url = showing.checkout_url.rstrip("/") + "/seats"
        self.throttle.before_request(seats_url)

        page = self.session.page()
        try:
            resp = page.goto(seats_url, wait_until="domcontentloaded", timeout=30000)
            status = resp.status if resp else 0
            # The seatingLayout streams in the RSC payload — wait for it to appear
            # rather than a fixed sleep, so we don't miss slow-streaming pages.
            try:
                page.wait_for_function(
                    "() => document.documentElement.innerHTML.includes('seatingLayout')",
                    timeout=12000)
            except Exception:
                page.wait_for_timeout(2000)  # fall back to a short settle
            html = page.content()
            shot = IMAGES_DIR / f"{showing.id.replace(':', '_')}.png"
            page.screenshot(path=str(shot), full_page=True)
        finally:
            page.close()

        blocked = looks_blocked(html, status)
        # Feed the throttle a 403 on a block so its backoff kicks in hard; also
        # drop the browsing context so the next request starts with clean cookies.
        self.throttle.note_result(seats_url, 403 if blocked else status)
        if blocked:
            self.session.reset()

        if recon:
            RECON_DIR.mkdir(exist_ok=True)
            (RECON_DIR / f"seats-{showing.id.replace(':', '_')}.html").write_text(html)
            print(f"[amc] recon: saved seats HTML + screenshot for {showing.id}")

        if blocked:
            print(f"[amc] {showing.id}: ⚠ BLOCKED by Cloudflare — backing off, skipping")
            return []

        layout = extract_seating_layout(html)
        seats = self._parse_seats(showing, layout)
        free = sum(1 for s in seats if s.status == SeatStatus.AVAILABLE)
        print(f"[amc] {showing.id}: {len(seats)} seats, {free} available "
              f"({'grid %dx%d' % (layout['columns'], layout['rows']) if layout else 'no layout found'})")
        return seats

    def _parse_seats(self, showing: Showing, layout: dict | None) -> Sequence[Seat]:
        """Map AMC's seatingLayout -> normalized Seat[]. Skips non-seats."""
        if not layout:
            return []
        out: list[Seat] = []
        for s in layout.get("seats", []):
            if not s.get("shouldDisplay"):
                continue  # NotASeat / structural gap
            name = s.get("name") or f"R{s['row']}C{s['column']}"
            m = re.match(r"([A-Za-z]+)(\d+)", name)
            row_label = m.group(1) if m else str(s["row"])
            num = int(m.group(2)) if m else int(s["column"])
            out.append(Seat(
                showing_id=showing.id,
                seat_id=name,
                section=s.get("seatTier", "Regular"),
                row=row_label,
                num=num,
                x=float(s["column"]),        # physical grid position (left-right)
                y=float(s["row"]),            # row 1 = front (nearest screen)
                seat_type=_SEAT_TYPE_MAP.get(s.get("type"), SeatType.STANDARD),
                status=SeatStatus.AVAILABLE if s.get("available") else SeatStatus.TAKEN,
            ))
        return out


if __name__ == "__main__":
    def _arg(flag: str, default: str) -> str:
        return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default

    a = AMCAdapter()
    date = _arg("--date", _date.today().isoformat())
    dump = "--dump" in sys.argv

    # --films: every film playing this venue + the slug AMC publishes for it. Run
    # this before repointing film.py at a new title.
    if "--films" in sys.argv:
        target = film_slug(_arg("--film", film_cfg.FILM))
        print(f"[amc:{a.venue['slug']}] films on {date} (* = matches {target!r}):")
        for slug, n in a.list_films(date, dump=dump):
            print(f"  {'*' if slug_matches(slug, target) else ' '} {n:3}  {slug}")
        sys.exit(0)

    showings = a.discover(_arg("--film", film_cfg.FILM), date, dump=dump)
    for sh in showings:
        print(f"[amc] {sh.fmt:11} {sh.auditorium:24} {sh.start_time}  {sh.checkout_url}")
    if "--recon" in sys.argv and showings:
        print(f"[amc] recon on first showing: {showings[0].id}")
        a.fetch_seats(showings[0], recon=True)
