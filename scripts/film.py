"""Which film this build targets — the one knob that repoints the whole engine.

Everything downstream (ingest, report, snapshot, API, website) takes its `--film`
default from `FILM`, so repointing at a new release is this line plus the `<h1>` in
`web/index.html`.

The AMC adapter matches on AMC's *own published slug*, which is not always the
marketing title slugified. Confirm a new title's slug against a live page first:

    python scripts/adapters/amc.py --films             # what's playing today + slugs
    python scripts/adapters/amc.py --films --date 2026-08-07
"""
from __future__ import annotations

FILM = "Spider-Man: Brand New Day"
# -> film_slug() gives "spider-man-brand-new-day"; confirmed live at AMC Lincoln
#    Square 2026-07-30 (41 showtimes) and 2026-07-31 (34). Wide release 2026-07-31.

# AMC lists premium/special screenings as SEPARATE films whose slug extends the
# base one, e.g. "spider-man-brand-new-day-dolby-opening-night-fan-event". Those
# are real showings of this movie with real seat maps, so we match them by prefix.
# Exact-match-only would silently drop them (an opening-night fan event is exactly
# the kind of showing you want a seat finder to surface).
#
# Set False if a title's slug is a prefix of some *unrelated* film's slug, where
# prefix matching would over-collect (e.g. a "…-2" sequel sharing the base slug).
MATCH_EVENT_LISTINGS = True

# Formats a default `report.py` run fetches seat maps for. This is a POLITENESS
# bound as much as a taste one: every extra format multiplies seat-map fetches, and
# AMC's floor is ~15s each.
#
# Brand New Day has NO 70mm print — the Odyssey build defaulted to IMAX_70MM, which
# on this film matches zero showings. Confirmed live at Lincoln Square 2026-07-30:
# IMAX_LASER 28 showtimes, STANDARD 9, DOLBY 5.
DEFAULT_FORMATS = "IMAX_LASER,DOLBY"

# NOTE, unchanged on purpose: adapters/base.py FORMAT_WEIGHT still ranks DOLBY
# (0.95) above IMAX_LASER (0.88), which was right when 70mm film was the trophy and
# "laser" meant the lesser digital IMAX. If you consider Lincoln Square's IMAX house
# the trophy for a tentpole like this, raise IMAX_LASER above DOLBY there — it
# decides which format wins the single "best seat overall" pick.

