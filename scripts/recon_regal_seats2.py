"""Regal seat recon step 2: from the movie page (?site&id&date), click through to
seat selection and capture the booking backend (webbooking.regmovies.com) traffic
+ whether Cloudflare Turnstile gates it. Decides if seats are reachable politely.

    python scripts/recon_regal_seats2.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rate

RECON_DIR = Path(__file__).resolve().parent / "recon"
IMAGES_DIR = Path(__file__).resolve().parent.parent / "images"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")


def main() -> None:
    from playwright.sync_api import sync_playwright

    # RPX 11pm perf on the movie page, showtime pre-selected.
    url = ("https://www.regmovies.com/movies/the-odyssey-ho00019072"
           "?site=1412&id=151761&date=07-17-2026")
    RECON_DIR.mkdir(exist_ok=True); IMAGES_DIR.mkdir(exist_ok=True)

    reqs: list[dict] = []
    booking: list[dict] = []
    turnstile = []
    rate.PoliteThrottle().before_request(url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(user_agent=_UA, locale="en-US",
                                   viewport={"width": 402, "height": 874},
                                   is_mobile=True, has_touch=True).new_page()

        def on_request(req):
            if req.resource_type in ("xhr", "fetch"):
                reqs.append(req.url)
            if "challenges.cloudflare.com/turnstile" in req.url:
                turnstile.append(req.url)

        def on_response(resp):
            host = urlparse(resp.url).netloc
            if "webbooking" in host or "vcdn.regmovies" in host:
                rec = {"url": resp.url, "status": resp.status}
                if "json" in (resp.headers or {}).get("content-type", ""):
                    try:
                        rec["body"] = resp.json()
                    except Exception:
                        rec["note"] = "unparseable"
                booking.append(rec)

        page.on("request", on_request)
        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3500)

        # Dismiss the OneTrust cookie banner (it intercepts pointer events).
        for sel in ["#onetrust-accept-btn-handler", "button:has-text('Accept All')"]:
            try:
                if page.locator(sel).count():
                    page.locator(sel).first.click(timeout=4000)
                    page.wait_for_timeout(800)
                    break
            except Exception:
                pass

        # Try the booking CTA: a showtime chip for this perf, or a Get Tickets button.
        clicked = None
        for sel in ["#showtime-mobile-0", "#seat-selector-handle-mobile",
                    "button[title='Select Seats']", "button:has-text('11:00pm')"]:
            loc = page.locator(sel)
            if loc.count():
                clicked = sel
                try:
                    loc.first.scroll_into_view_if_needed(timeout=4000)
                    loc.first.click(timeout=8000)
                except Exception as e:
                    clicked = f"{sel} (click err: {e})"
                break
        page.wait_for_timeout(8000)
        landing = page.url
        html = page.content()
        (RECON_DIR / "regal-seats2.html").write_text(html)
        page.screenshot(path=str(IMAGES_DIR / "regal-seats2.png"), full_page=True)
        browser.close()

    (RECON_DIR / "regal-seats2.json").write_text(json.dumps(
        {"landing": landing, "clicked": clicked, "booking_responses": booking,
         "turnstile_hits": len(turnstile), "n_xhr": len(reqs)}, indent=2))

    print(f"[recon] clicked: {clicked}")
    print(f"[recon] landed: {landing}")
    print(f"[recon] Turnstile (CAPTCHA) requests: {len(turnstile)}")
    print(f"[recon] webbooking/vcdn responses: {len(booking)}")
    for b in booking[:12]:
        u = urlparse(b["url"])
        keys = list(b["body"].keys()) if isinstance(b.get("body"), dict) else b.get("note", "")
        print(f"    {b['status']} {u.netloc}{u.path[:64]}  {str(keys)[:70]}")
    # Any seat plan signal in HTML?
    for k in ("SeatLayoutData", "seatLayout", "AreaCategory", "SeatsLayout", "PhysicalName"):
        c = html.count(k)
        if c:
            print(f"    HTML contains {k!r} x{c}")
    print(f"[recon] saved -> {RECON_DIR}/regal-seats2.json (+ .html, screenshot)")


if __name__ == "__main__":
    main()
