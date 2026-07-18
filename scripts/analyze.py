"""Seat quality scorer: geometry + format/section (no fill-order / revealed pref).

quality(seat) = w_geo * geometry(seat) * w_format(showing) * type_bonus(seat)

Only ranks AVAILABLE seats. Geometry needs the auditorium's screen position; until
that's calibrated per auditorium we approximate the screen as centered at the
front (min y). Refine screen_center_x / screen_y on the Showing once known.
"""
from __future__ import annotations

from adapters.base import FORMAT_WEIGHT, Seat, SeatStatus, SeatType

# Seat-type multipliers (recliners/premium are more comfortable, all else equal).
_TYPE_BONUS = {
    SeatType.PREMIUM: 1.10,
    SeatType.RECLINER: 1.05,
    SeatType.LOVESEAT: 1.00,
    SeatType.STANDARD: 1.00,
    SeatType.ACCESSIBLE: 0.95,
    SeatType.COMPANION: 0.95,
}

# Ideal viewing: horizontally centered, ~2/3 back into the room.
_IDEAL_DEPTH_FRAC = 0.66


def _geometry_score(seat: Seat, xs: list[float], ys: list[float],
                    screen_center_x: float | None) -> float:
    """0..1. Penalize off-center and being too close/too far from the screen."""
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    cx = screen_center_x if screen_center_x is not None else (x_min + x_max) / 2
    x_span = (x_max - x_min) or 1.0
    y_span = (y_max - y_min) or 1.0

    # Horizontal: 1 at center, falls off toward the walls.
    x_off = abs(seat.x - cx) / (x_span / 2)
    x_score = max(0.0, 1.0 - x_off ** 2)

    # Depth: 1 at the ideal fraction back, falls off toward front/back rows.
    depth_frac = (seat.y - y_min) / y_span   # 0 = front (nearest screen), 1 = back
    d_off = abs(depth_frac - _IDEAL_DEPTH_FRAC) / max(_IDEAL_DEPTH_FRAC, 1 - _IDEAL_DEPTH_FRAC)
    d_score = max(0.0, 1.0 - d_off ** 2)

    return 0.5 * x_score + 0.5 * d_score


# Seats reserved for specific needs — excluded from a general "best seat" pick by
# default (they're also what remains when a show is nearly sold out, so they'd
# otherwise dominate the ranking). Pass include_accessible=True to keep them.
_RESERVED_TYPES = {SeatType.ACCESSIBLE, SeatType.COMPANION}


def rank(seats: list[Seat], fmt: str, screen_center_x: float | None = None,
         top: int | None = None, include_accessible: bool = False) -> list[tuple[Seat, float]]:
    """Return available seats sorted best-first with their quality score.

    Accessible/companion seats are excluded unless include_accessible=True.
    """
    avail = [s for s in seats if s.status == SeatStatus.AVAILABLE
             and (include_accessible or s.seat_type not in _RESERVED_TYPES)]
    if not avail:
        return []
    xs = [s.x for s in avail]
    ys = [s.y for s in avail]
    w_fmt = FORMAT_WEIGHT.get(fmt, 0.5)

    scored = [
        (s, _geometry_score(s, xs, ys, screen_center_x)
            * w_fmt
            * _TYPE_BONUS.get(s.seat_type, 1.0))
        for s in avail
    ]
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:top] if top else scored
