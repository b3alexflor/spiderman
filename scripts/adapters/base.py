"""Shared types + the Adapter protocol every chain implements.

Each chain adapter owns BOTH discovery (what's showing) and seat-fetch (the live
map). Everything below is chain-agnostic: the normalized Showing/Seat records, the
format quality weights, and the Adapter interface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence


# --- Format quality weights -------------------------------------------------
# 70mm IMAX is the trophy; Dolby Cinema is near-equal value. Both top-tier.
FORMAT_WEIGHT: dict[str, float] = {
    "IMAX_70MM": 1.00,   # trophy — actual 70mm film in the IMAX house
    "DOLBY": 0.95,       # near-equal value
    "IMAX_LASER": 0.88,  # "Laser at AMC" — IMAX digital laser (premium, not 70mm film)
    "IMAX_DIGITAL": 0.80,
    "PRIME": 0.70,       # Prime / large-format non-IMAX
    "STANDARD": 0.50,
}


# --- Seat vocabulary --------------------------------------------------------
class SeatStatus:
    AVAILABLE = "available"
    TAKEN = "taken"
    HELD = "held"          # in someone's cart / temporarily blocked
    BROKEN = "broken"      # out of service
    UNKNOWN = "unknown"


class SeatType:
    STANDARD = "standard"
    RECLINER = "recliner"
    PREMIUM = "premium"
    LOVESEAT = "loveseat"
    ACCESSIBLE = "accessible"
    COMPANION = "companion"


@dataclass(frozen=True)
class Showing:
    """One screening of the film in one auditorium at one time."""
    id: str                       # stable per-chain id (chain-prefixed, e.g. "amc:<showtimeId>")
    theater: str                  # e.g. "AMC Lincoln Square 13"
    auditorium: str               # e.g. "IMAX" / "Dolby Cinema" / "Theatre 5"
    film: str                     # "The Odyssey"
    fmt: str                      # key into FORMAT_WEIGHT
    start_time: str               # ISO 8601 local, e.g. "2026-07-17T19:30:00"
    checkout_url: str             # URL that leads to the seat map
    # Screen geometry, filled once known per auditorium (for the geometry scorer):
    screen_center_x: float | None = None   # in the same coord space as Seat.x
    screen_y: float | None = None          # y of the screen plane


@dataclass(frozen=True)
class Seat:
    showing_id: str
    seat_id: str                  # stable within a showing, e.g. "H12"
    section: str                  # e.g. "Main", "Balcony", "IMAX-Center"
    row: str                      # "H"
    num: int                      # 12
    x: float                      # layout coordinate
    y: float                      # layout coordinate (larger = farther from screen, by convention)
    seat_type: str = SeatType.STANDARD
    status: str = SeatStatus.UNKNOWN


class Adapter(Protocol):
    """Every chain implements this. Nothing else in the pipeline knows the chain."""

    name: str  # short slug, e.g. "amc"

    def discover(self, film: str, date: str) -> Sequence[Showing]:
        """Return today's showings of `film` for this chain's target theaters."""
        ...

    def fetch_seats(self, showing: Showing) -> Sequence[Seat]:
        """Drive the checkout for `showing` and return its live seat map."""
        ...
