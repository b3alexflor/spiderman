"""One-shot recon of the AMC seat-selection flow (phase 1: MAP, don't parse).

Picks a live IMAX 70mm Odyssey showing, opens its checkout page, and records:
  - every XHR/fetch request URL (to find the seat/availability endpoint)
  - every JSON response (full body for seat-ish URLs, else url+keys+size)
  - the rendered HTML + a screenshot
  - the interactive controls present (buttons/links text) so we can design the
    ticket-quantity -> seat-map click-through in phase 2

Outputs to scripts/recon/. Single throttled checkout hit. Politeness first.

    python scripts/recon_seatflow.py           # auto-pick first IMAX 70mm showing
    python scripts/recon_seatflow.py 134717192 # or a specific showtime id
"""
from __future__ import annotations

import json
import sys
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rate
import film as film_cfg
from adapters import amc

RECON_DIR = Path(__file__).resolve().parent / "recon"
IMAGES_DIR = Path(__file__).resolve().parent.parent / "images"
_SEAT_HINTS = ("seat", "availab", "auditorium", "layout", "reserv")


def pick_showtime(explicit: str | None) -> tuple[str, str]:
    """Return (showtime_id, checkout_url) — explicit id, or first live IMAX 70mm."""
    if explicit:
        return explicit, amc.CHECKOUT_URL.format(showtime_id=explicit)
    a = amc.AMCAdapter()
    showings = a.discover(film_cfg.FILM, _date.today().isoformat())
    imax = [s for s in showings if s.fmt == "IMAX_70MM"] or showings
    if not imax:
        raise SystemExit("no showings discovered")
    s = imax[0]
    print(f"[recon] picked {s.fmt} {s.start_time} -> {s.checkout_url}")
    return s.id.split(":")[-1], s.checkout_url


def main() -> None:
    from playwright.sync_api import sync_playwright

    explicit = next((a for a in sys.argv[1:] if a.isdigit()), None)
    sid, url = pick_showtime(explicit)
    RECON_DIR.mkdir(exist_ok=True)
    IMAGES_DIR.mkdir(exist_ok=True)

    requests: list[dict] = []
    responses: list[dict] = []
    throttle = rate.PoliteThrottle()
    throttle.before_request(url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(
            user_agent="Mozilla/5.0 (personal-use seat-scraper; low volume)"
        ).new_page()

        def on_request(req):
            if req.resource_type in ("xhr", "fetch"):
                requests.append({"method": req.method, "url": req.url,
                                 "type": req.resource_type})

        def on_response(resp):
            ctype = (resp.headers or {}).get("content-type", "")
            if "json" not in ctype:
                return
            rec: dict = {"url": resp.url, "status": resp.status}
            low = resp.url.lower()
            try:
                body = resp.json()
            except Exception:
                rec["note"] = "unparseable json"
                responses.append(rec)
                return
            if any(h in low for h in _SEAT_HINTS):
                rec["body"] = body  # full body for seat-ish endpoints
            else:
                rec["keys"] = list(body.keys()) if isinstance(body, dict) else f"[{type(body).__name__}]"
                rec["size"] = len(json.dumps(body))
            responses.append(rec)

        page.on("request", on_request)
        page.on("response", on_response)
        resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        throttle.note_result(url, resp.status if resp else 0)
        page.wait_for_timeout(4000)  # let the checkout widget's XHRs fire

        # Harvest interactive controls so we can design the click-through.
        controls = page.evaluate("""() => {
          const grab = el => ({
            tag: el.tagName.toLowerCase(),
            text: (el.textContent||'').replace(/\\s+/g,' ').trim().slice(0,50),
            aria: el.getAttribute('aria-label')||'',
            testid: el.getAttribute('data-testid')||'',
            name: el.getAttribute('name')||'',
          });
          const els = Array.from(document.querySelectorAll('button, a[role=button], select, input[type=number], [data-testid]'));
          return els.slice(0, 60).map(grab);
        }""")

        (RECON_DIR / f"seatflow-{sid}.html").write_text(page.content())
        shot = IMAGES_DIR / f"seatflow-{sid}.png"
        page.screenshot(path=str(shot), full_page=True)
        browser.close()

    out = {
        "showtime_id": sid, "checkout_url": url,
        "xhr_requests": requests,
        "json_responses": responses,
        "controls": controls,
    }
    (RECON_DIR / f"seatflow-{sid}.json").write_text(json.dumps(out, indent=2))

    # Console summary
    seat_urls = [r["url"] for r in responses if any(h in r["url"].lower() for h in _SEAT_HINTS)]
    print(f"[recon] {len(requests)} xhr/fetch, {len(responses)} json responses")
    print(f"[recon] seat-ish endpoints ({len(seat_urls)}):")
    for u in seat_urls[:15]:
        print(f"          {u}")
    print(f"[recon] saved -> {RECON_DIR}/seatflow-{sid}.json  (+ .html, screenshot)")
    print(f"[recon] controls sample: "
          + ", ".join(c["text"] or c["aria"] or c["testid"] for c in controls[:12] if any(c.values())))


if __name__ == "__main__":
    main()
