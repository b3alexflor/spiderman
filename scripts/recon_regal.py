"""Recon Regal (regmovies.com) — map discovery + seat flow before building regal.py.

Regal has aggressive anti-bot (plain robots.txt fetch 403s), so we drive a real
browser. This loads a theatre's showtimes page, records every XHR/fetch + JSON
response (to find the getShowtimes API and any seat endpoint), and dumps HTML.

    python scripts/recon_regal.py                 # Essex Crossing (1412)
    python scripts/recon_regal.py 1412 2026-07-17
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

# Known Manhattan Regal theatre ids (from cited source pages / venues.py).
THEATRES = {
    "1412": "regal-essex-crossing",
    "1335": "regal-battery-park",
}


def main() -> None:
    from playwright.sync_api import sync_playwright

    tid = next((a for a in sys.argv[1:] if a.isdigit()), "1412")
    date = next((a for a in sys.argv[1:] if "-" in a), "2026-07-17")
    slug = THEATRES.get(tid, f"regal-{tid}")
    url = f"https://www.regmovies.com/theatres/{slug}-{tid}"
    RECON_DIR.mkdir(exist_ok=True)
    IMAGES_DIR.mkdir(exist_ok=True)

    requests: list[dict] = []
    responses: list[dict] = []
    throttle = rate.PoliteThrottle()
    throttle.before_request(url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(user_agent=_UA, locale="en-US").new_page()

        def on_request(req):
            if req.resource_type in ("xhr", "fetch"):
                requests.append({"method": req.method, "url": req.url})

        def on_response(resp):
            if "json" not in (resp.headers or {}).get("content-type", ""):
                return
            rec = {"url": resp.url, "status": resp.status}
            try:
                body = resp.json()
            except Exception:
                responses.append({**rec, "note": "unparseable"}); return
            if isinstance(body, dict):
                rec["keys"] = list(body.keys())
            elif isinstance(body, list):
                rec["keys"] = f"[list of {len(body)}]"
            rec["size"] = len(json.dumps(body))
            # Keep full body for the showtimes API (small enough, most useful).
            if "showtime" in resp.url.lower() or "getshow" in resp.url.lower():
                rec["body"] = body
            responses.append(rec)

        page.on("request", on_request)
        page.on("response", on_response)
        resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        status = resp.status if resp else 0
        throttle.note_result(url, status)
        page.wait_for_timeout(5000)  # let showtime XHRs fire

        title = page.title()
        (RECON_DIR / f"regal-{tid}.html").write_text(page.content())
        page.screenshot(path=str(IMAGES_DIR / f"regal-{tid}.png"), full_page=True)
        browser.close()

    (RECON_DIR / f"regal-{tid}.json").write_text(
        json.dumps({"url": url, "status": status, "title": title,
                    "xhr_requests": requests, "json_responses": responses}, indent=2))

    print(f"[recon] status={status}  title={title!r}")
    print(f"[recon] {len(requests)} xhr/fetch, {len(responses)} json responses")
    print("[recon] regmovies API endpoints seen:")
    for r in requests:
        h = urlparse(r["url"])
        if "regmovies" in h.netloc:
            print(f"          {r['method']} {h.path}{'?' + h.query[:60] if h.query else ''}")
    print("[recon] json responses (regmovies):")
    for r in responses:
        if "regmovies" in urlparse(r["url"]).netloc:
            print(f"          {r['status']} {urlparse(r['url']).path}  keys={r.get('keys')}")
    print(f"[recon] saved -> {RECON_DIR}/regal-{tid}.json (+ .html, screenshot)")


if __name__ == "__main__":
    main()
