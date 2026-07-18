"""Per-host polite throttle. Shared by every adapter and the probe.

Design stance: we are a personal-use, low-volume scraper. No site here publishes a
crawl-delay, so we SELF-IMPOSE a conservative floor, add jitter (so we don't beat
like a metronome), serialize per host, and back off hard on any throttle signal
(429/403/503, Retry-After). When unsure, slower.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

# Conservative defaults. Regal 403s plain fetches (anti-bot), so it gets a slower
# floor than AMC. Tune from probe.py results, never below these.
DEFAULT_MIN_INTERVAL = 8.0     # seconds between requests to the same host
PER_HOST_MIN_INTERVAL = {
    "www.regmovies.com": 20.0,  # stricter anti-bot observed
    "www.amctheatres.com": 15.0,  # Cloudflare challenged us at 8s under load; back off
}
JITTER_FRAC = 0.4              # +/- 40% random jitter on each interval
MAX_BACKOFF = 300.0           # cap exponential backoff at 5 min
THROTTLE_STATUSES = {429, 403, 503}


def host_of(url: str) -> str:
    return urlparse(url).netloc.lower()


@dataclass
class _HostState:
    last_request: float = 0.0     # time.monotonic() of last request start
    backoff: float = 0.0          # extra seconds forced by throttle signals


@dataclass
class PoliteThrottle:
    min_interval: float = DEFAULT_MIN_INTERVAL
    jitter_frac: float = JITTER_FRAC
    _hosts: dict[str, _HostState] = field(default_factory=dict)

    def _floor(self, host: str) -> float:
        return max(self.min_interval, PER_HOST_MIN_INTERVAL.get(host, 0.0))

    def before_request(self, url: str) -> float:
        """Block until it's polite to hit `url`'s host. Returns seconds waited."""
        host = host_of(url)
        st = self._hosts.setdefault(host, _HostState())
        base = self._floor(host) + st.backoff
        gap = base * (1 + random.uniform(-self.jitter_frac, self.jitter_frac))
        elapsed = time.monotonic() - st.last_request
        wait = max(0.0, gap - elapsed)
        if wait:
            time.sleep(wait)
        st.last_request = time.monotonic()
        return wait

    def note_result(self, url: str, status: int, retry_after: float | None = None) -> None:
        """Feed back the response so we escalate/relax backoff for this host."""
        st = self._hosts.setdefault(host_of(url), _HostState())
        if status in THROTTLE_STATUSES:
            if retry_after is not None:
                st.backoff = min(MAX_BACKOFF, max(st.backoff, retry_after))
            else:
                st.backoff = min(MAX_BACKOFF, (st.backoff or self.min_interval) * 2)
        elif 200 <= status < 300:
            st.backoff = 0.0  # healthy — clear penalties


def parse_retry_after(headers: dict[str, str]) -> float | None:
    """Retry-After as seconds (delta form only; HTTP-date form ignored here)."""
    val = (headers or {}).get("retry-after") or (headers or {}).get("Retry-After")
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None
