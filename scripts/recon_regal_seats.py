"""Recon the Regal booking/seat flow: click an Odyssey showtime, capture the seat
source. Odyssey is Film[0] on the theatre page, so its showtime buttons are
id^='show0time'. We click one, then record the resulting URL, every JSON response
(full body for seat-ish ones), any __NEXT_DATA__ on the landing page, and HTML.

    python scripts/recon_regal_seats.py            # Essex Crossing (1412)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rate

RECON_DIR = Path(__file__).resolve().parent / "recon"
IMAGES_DIR = Path(__file__).resolve().parent.parent / "images"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")
_SEAT_HINTS = ("seat", "layout", "availab", "session", "performance", "booking",
               "ticket", "plan", "area")


def main() -> None:
    from playwright.sync_api import sync_playwright

    code = next((a for a in sys.argv[1:] if a.isdigit()), "1412")
    url = f"https://www.regmovies.com/theatres/regal-essex-crossing-{code}"
    RECON_DIR.mkdir(exist_ok=True)
    IMAGES_DIR.mkdir(exist_ok=True)

    requests: list[dict] = []
    responses: list[dict] = []
    throttle = rate.PoliteThrottle()
    throttle.before_request(url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=_UA, locale="en-US")
        page = ctx.new_page()

        def on_request(req):
            if req.resource_type in ("xhr", "fetch"):
                requests.append({"method": req.method, "url": req.url})

        def on_response(resp):
            low = resp.url.lower()
            if "json" not in (resp.headers or {}).get("content-type", ""):
                return
            rec = {"url": resp.url, "status": resp.status}
            try:
                body = resp.json()
            except Exception:
                responses.append({**rec, "note": "unparseable"}); return
            rec["keys"] = (list(body.keys()) if isinstance(body, dict)
                           else f"[list {len(body)}]" if isinstance(body, list) else str(type(body)))
            if any(h in low for h in _SEAT_HINTS):
                rec["body"] = body
            responses.append(rec)

        page.on("request", on_request)
        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3000)

        # Click the first Odyssey (Film[0]) showtime button.
        btns = page.locator("button[id^='show0time']")
        n = btns.count()
        print(f"[recon] found {n} Odyssey showtime buttons")
        clicked_label = None
        if n:
            b = btns.first
            clicked_label = b.get_attribute("aria-label")
            print(f"[recon] clicking: {clicked_label!r}")
            try:
                b.scroll_into_view_if_needed(timeout=5000)
                b.click(timeout=8000)
            except Exception as e:
                print(f"[recon] click issue: {e}")
            # Booking flow may navigate same tab or open a popup.
            page.wait_for_timeout(7000)

        landing = page.url
        # If a popup opened, prefer it.
        if len(ctx.pages) > 1:
            page = ctx.pages[-1]
            page.wait_for_timeout(2000)
            landing = page.url

        html = page.content()
        (RECON_DIR / f"regal-seats-{code}.html").write_text(html)
        page.screenshot(path=str(IMAGES_DIR / f"regal-seats-{code}.png"), full_page=True)
        browser.close()

    # Look for embedded seat data on the landing page.
    nd = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    seatish_html = sum(html.lower().count(k) for k in ("seat", "row"))

    out = {"start_url": url, "landing_url": landing, "clicked": clicked_label,
           "xhr_requests": requests, "json_responses": responses}
    (RECON_DIR / f"regal-seats-{code}.json").write_text(json.dumps(out, indent=2))

    print(f"\n[recon] landed on: {landing}")
    print(f"[recon] {len(requests)} xhr, {len(responses)} json responses")
    print("[recon] seat-ish JSON responses (full body saved):")
    for r in responses:
        if "body" in r:
            print(f"    {r['status']} {urlparse(r['url']).netloc}{urlparse(r['url']).path}  keys={r['keys']}")
    print(f"[recon] landing has __NEXT_DATA__: {bool(nd)} | 'seat'+'row' count in HTML: {seatish_html}")
    print(f"[recon] saved -> {RECON_DIR}/regal-seats-{code}.json (+ .html, screenshot)")


if __name__ == "__main__":
    main()
