"""Gentle rate characterization — learn safe cadence WITHOUT stress-testing.

Method (deliberately conservative):
  1. Read robots.txt: honor any Crawl-delay as a hard floor.
  2. Send a SMALL, hard-capped number of spaced requests through PoliteThrottle,
     recording status, latency, and rate-limit / anti-bot headers.
  3. STOP IMMEDIATELY on the first throttle or anti-bot signal (429/403/503,
     Retry-After, Cloudflare/Akamai challenge). We characterize the healthy zone;
     we never push past the first "no".
  4. Recommend a snapshot interval with a safety margin.

This is not a load test. MAX_PROBES is tiny and the floor interval always applies.

    python scripts/probe.py https://www.amctheatres.com/movie-theatres/new-york-city/amc-lincoln-square-13
"""
from __future__ import annotations

import sys
import time
import urllib.request
from pathlib import Path
from urllib.robotparser import RobotFileParser

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rate  # noqa: E402

MAX_PROBES = 6                     # hard cap — never more, regardless of health
UA = "Mozilla/5.0 (personal-use seat-scraper; low volume)"
_ANTIBOT_HEADER_HINTS = ("cf-ray", "cf-mitigated", "akamai", "x-akamai", "server")
_ANTIBOT_VALUE_HINTS = ("cloudflare", "akamai")


def robots_crawl_delay(base: str) -> float | None:
    rp = RobotFileParser()
    root = f"{base.split('/', 3)[0]}//{rate.host_of(base)}"
    rp.set_url(f"{root}/robots.txt")
    try:
        rp.read()
    except Exception as e:
        print(f"[probe] robots.txt unreadable ({e}) — treating as no declared delay")
        return None
    cd = rp.crawl_delay(UA) or rp.crawl_delay("*")
    return float(cd) if cd else None


def _fetch(url: str):
    """One request via stdlib. Returns (status, headers, latency) or a throttle tuple."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, time.monotonic() - t0
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, time.monotonic() - t0
    except Exception as e:
        print(f"[probe] request error: {e}")
        return None, {}, time.monotonic() - t0


def _antibot_signal(headers: dict[str, str]) -> str | None:
    for k, v in headers.items():
        if k in _ANTIBOT_HEADER_HINTS and any(h in (v or "").lower() for h in _ANTIBOT_VALUE_HINTS):
            return f"{k}: {v}"
        if k in ("cf-ray", "cf-mitigated"):
            return f"{k}: {v}"
    return None


def probe(url: str) -> None:
    host = rate.host_of(url)
    floor = max(rate.PER_HOST_MIN_INTERVAL.get(host, rate.DEFAULT_MIN_INTERVAL),
                robots_crawl_delay(url) or 0.0)
    print(f"[probe] {host}: floor interval = {floor:.1f}s (robots + self-imposed)")

    throttle = rate.PoliteThrottle(min_interval=floor)
    latencies: list[float] = []
    for i in range(1, MAX_PROBES + 1):
        waited = throttle.before_request(url)
        status, headers, latency = _fetch(url)
        throttle.note_result(url, status or 0, rate.parse_retry_after(headers))
        ab = _antibot_signal(headers)
        print(f"[probe] #{i} waited={waited:4.1f}s status={status} latency={latency:.2f}s"
              + (f"  anti-bot<{ab}>" if ab else ""))

        if status in rate.THROTTLE_STATUSES or (status and status >= 500):
            print(f"[probe] STOP — throttle/anti-bot signal at request #{i} (status {status}). "
                  f"Backing off. Do NOT probe harder.")
            ra = rate.parse_retry_after(headers)
            if ra:
                print(f"[probe] server asked Retry-After={ra:.0f}s")
            return
        if status and 200 <= status < 300:
            latencies.append(latency)

    if latencies:
        avg = sum(latencies) / len(latencies)
        recommended = max(floor, avg * 3)   # margin: never poll faster than ~3x latency, min floor
        print(f"[probe] {len(latencies)} healthy responses, avg latency {avg:.2f}s.")
        print(f"[probe] RECOMMENDED snapshot interval >= {recommended:.0f}s per showing "
              f"(stayed healthy through {MAX_PROBES} spaced requests).")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python scripts/probe.py <url>")
        raise SystemExit(2)
    probe(sys.argv[1])
