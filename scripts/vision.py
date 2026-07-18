"""Screenshot -> seats fallback, for sites with no clean seat XHR.

Used only when an adapter can't intercept structured seat data (bespoke indie
systems: Metrograph, Film Forum, Paris). The adapter hands us a seat-map
screenshot; we return normalized Seat[] parsed from the image. Stub until first
needed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from adapters.base import Seat, Showing


def parse_screenshot(showing: Showing, image_path: Path) -> Sequence[Seat]:
    """TODO: parse a seat-map screenshot into Seat[] (grid detection + status-by-
    color classification). Wire up when the first no-XHR chain is added."""
    raise NotImplementedError("vision fallback not implemented yet")
