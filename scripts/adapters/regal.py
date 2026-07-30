"""Regal (regmovies.com) adapter. Second chain — anti-bot, browser-only.

discover() is WIRED + offline-verifiable: Regal is Next.js and embeds the full
schedule in <script id="__NEXT_DATA__"> (clean JSON, unlike AMC's escaped RSC). We
read props.pageProps.showtimes[] -> Film[] -> Performances[]. Each performance is a
session: PerformanceId, CalendarShowTime (already LOCAL ISO — no tz math),
PerformanceAttributes (format/features), StopSales, Auditorium.

fetch_seats() is a RECON SHELL: the seat map loads only after driving the booking
flow (client-side route, no static URL). Cracking it needs a booking-flow recon
like AMC's; see recon_regal.py. Discovery works today.

    python scripts/adapters/regal.py                 # Essex Crossing discover
    python scripts/adapters/regal.py --dump
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date as _date
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rate
import film as film_cfg
from browser import BrowserSession
from adapters.base import Seat, Showing

RECON_DIR = Path(__file__).resolve().parent.parent / "recon"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")

# Manhattan Regal venues (theatre code -> route slug). Codes from cited sources.
VENUES = {
    "1412": {"name": "Regal Essex Crossing & RPX", "slug": "regal-essex-crossing"},
    "1335": {"name": "Regal Battery Park 11", "slug": "regal-battery-park"},
}
DEFAULT_CODE = "1412"

# PerformanceAttributes token (lowercased) -> our FORMAT_WEIGHT key. Priority order;
# RPX/4DX/ScreenX are Regal premium large-formats (grouped as PRIME for now).
_REGAL_FORMAT = (
    ("imax 70mm", "IMAX_70MM"),
    ("imax", "IMAX_DIGITAL"),
    ("rpx", "PRIME"),
    ("4dx", "PRIME"),
    ("screenx", "PRIME"),
)

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


# --- Pure helpers (no browser) ---------------------------------------------
def extract_next_data(html: str) -> dict | None:
    m = _NEXT_DATA_RE.search(html or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return None


def format_from_attrs(attrs: list[str]) -> str:
    joined = " ".join(attrs).lower()
    for token, key in _REGAL_FORMAT:
        if token in joined:
            return key
    return "STANDARD"


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")


def deep_link(code: str, pid, title: str, master_code: str, date: str) -> str:
    """The human-facing Regal seat page for a performance (they pass the CAPTCHA).

    e.g. https://www.regmovies.com/movies/the-odyssey-ho00019072?site=1412&id=151761&date=07-17-2026
    """
    mmddyyyy = f"{date[5:7]}-{date[8:10]}-{date[0:4]}"  # YYYY-MM-DD -> MM-DD-YYYY
    return (f"https://www.regmovies.com/movies/{_slug(title)}-{(master_code or '').lower()}"
            f"?site={code}&id={pid}&date={mmddyyyy}")


def auditorium_label(attrs: list[str], fmt: str, aud: int) -> str:
    if fmt == "PRIME":
        for a in attrs:
            if a.upper() in ("RPX", "4DX", "SCREENX"):
                return a
    if fmt in ("IMAX_70MM", "IMAX_DIGITAL"):
        return "IMAX"
    return f"Auditorium {aud}"


def performances_to_showings(next_data: dict, film: str, date: str,
                             theater_name: str, theater_code: str) -> list[Showing]:
    """Parse __NEXT_DATA__ -> Showings for `film` on `date`. Pure/tested."""
    pp = (next_data or {}).get("props", {}).get("pageProps", {})
    groups = pp.get("showtimes", []) or []
    target = film.lower()
    out: list[Showing] = []
    for g in groups:
        if not str(g.get("AdvertiseShowDate", "")).startswith(date):
            continue
        for f in g.get("Film", []):
            if target not in (f.get("Title", "") or "").lower():
                continue
            title = f.get("Title", film)
            master = f.get("MasterMovieCode", "")
            for p in f.get("Performances", []):
                attrs = p.get("PerformanceAttributes", []) or []
                fmt = format_from_attrs(attrs)
                pid = p.get("PerformanceId")
                out.append(Showing(
                    id=f"regal:{pid}",
                    theater=theater_name,
                    auditorium=auditorium_label(attrs, fmt, p.get("Auditorium", 0)),
                    film=title,
                    fmt=fmt,
                    # CalendarShowTime is already local ISO ("2026-07-17T21:00:00").
                    start_time=p.get("CalendarShowTime", f"{date}T00:00:00"),
                    # Human-facing seat page (Regal seats are CAPTCHA-gated for bots).
                    checkout_url=deep_link(theater_code, pid, title, master, date),
                ))
    out.sort(key=lambda s: s.start_time)
    return out


class RegalAdapter:
    name = "regal"

    def __init__(self, code: str = DEFAULT_CODE,
                 throttle: rate.PoliteThrottle | None = None,
                 session: BrowserSession | None = None):
        self.code = code
        self.venue = VENUES.get(code, {"name": f"Regal ({code})", "slug": f"regal-{code}"})
        self.throttle = throttle or rate.PoliteThrottle()
        self.session = session or BrowserSession(user_agent=_UA)
        # __NEXT_DATA__ carries the FULL multi-day schedule; cache it per adapter
        # so a 3-day discover costs ONE page load, not three identical ones.
        self._next_data: dict | None = None

    @property
    def theatre_url(self) -> str:
        return f"https://www.regmovies.com/theatres/{self.venue['slug']}-{self.code}"

    def discover(self, film: str, date: str, *, dump: bool = False) -> Sequence[Showing]:
        if self._next_data is None:
            url = self.theatre_url
            self.throttle.before_request(url)
            page = self.session.page()
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
                status = resp.status if resp else 0
                self.throttle.note_result(url, status)
                if status >= 400:
                    print(f"[regal:{self.code}] HTTP {status} — blocked or bad code, skipping")
                    return []
                page.wait_for_timeout(2500)
                html = page.content()
            finally:
                page.close()

            if dump:
                RECON_DIR.mkdir(exist_ok=True)
                (RECON_DIR / f"regal-{self.code}-{date}.html").write_text(html)
                print(f"[regal:{self.code}] dump -> {RECON_DIR}/regal-{self.code}-{date}.html")

            self._next_data = extract_next_data(html)
            if not self._next_data:
                print(f"[regal:{self.code}] no __NEXT_DATA__ (block or markup change)")
                return []

        showings = performances_to_showings(self._next_data, film, date,
                                            self.venue["name"], self.code)
        print(f"[regal:{self.code}] discover: {len(showings)} {film!r} performances ({date})")
        return showings

    def fetch_seats(self, showing: Showing, *, recon: bool = False) -> Sequence[Seat]:
        """NOT SUPPORTED — Regal seats are CAPTCHA-gated (deliberate non-support).

        Recon finding (recon_regal_seats*.py): the seat plan lives on the Vista
        booking backend NEXT_PUBLIC_BOOKING_API=https://webbooking.regmovies.com,
        and the whole booking flow (movie page -> Select Seats) is protected by
        Cloudflare Turnstile (challenges.cloudflare.com/turnstile). The seat map
        cannot be reached without solving/bypassing that CAPTCHA.

        We do NOT do that: this project's stance is detect-and-back-off, not evade,
        and CAPTCHA-bypass is anti-bot circumvention. So Regal availability is out
        of scope. Regal DISCOVERY works (public __NEXT_DATA__); Regal SEATS don't.
        """
        print(f"[regal] fetch_seats unsupported for {showing.id}: seat plan is behind "
              "Cloudflare Turnstile on webbooking.regmovies.com (won't bypass CAPTCHA)")
        return []


if __name__ == "__main__":
    a = RegalAdapter()
    showings = a.discover(film_cfg.FILM, _date.today().isoformat(), dump="--dump" in sys.argv)
    for s in showings:
        print(f"  {s.fmt:12} {s.auditorium:16} {s.start_time[11:16]}  {s.id}")
