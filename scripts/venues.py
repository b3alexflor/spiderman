"""Manhattan movie venues (below 84th St), verified July 2026.

Roster source: hand-verified against live listings (Poor Stuart's guides, chain
sites, trade press) — three venues had closed/changed hands in the prior 18 months.

Purpose here: feed the per-chain adapters. Each adapter iterates the VENUES whose
`chain` it owns. AMC venues share one discovery pattern (only `slug` differs), so
amc.py should take a venue instead of hardcoding Lincoln Square.

`first_run` = plays wide releases like *The Odyssey* (the multiplexes). Arthouses
run rep/indie programming and are `first_run=False` — irrelevant to the Odyssey
goal, kept for when the project generalizes beyond one film.

CAUTION: AMC `slug`s below are inferred from the Lincoln Square pattern
(amc-<name>) and NOT all confirmed. A wrong slug 404s on discover — self-checking.
Confirm each with one `discover` call before trusting it. Regal URLs marked
CONFIRMED came from cited source pages.
"""
from __future__ import annotations

AMC_CITY = "new-york-city"  # path segment in amctheatres.com theatre URLs

VENUES: list[dict] = [
    # --- AMC (chain adapter: amc.py) --------------------------------------
    {"chain": "amc", "name": "AMC Lincoln Square 13", "slug": "amc-lincoln-square-13",
     "neighborhood": "Upper West Side", "first_run": True, "trophy": True,
     "slug_confirmed": True},  # confirmed live 2026-07-17 (70mm/Laser/Dolby Odyssey)
    {"chain": "amc", "name": "AMC Empire 25", "slug": "amc-empire-25",
     "neighborhood": "Times Square", "first_run": True, "slug_confirmed": True},
    {"chain": "amc", "name": "AMC 34th Street 14", "slug": "amc-34th-street-14",
     "neighborhood": "Midtown West", "first_run": True, "slug_confirmed": True},
    {"chain": "amc", "name": "AMC Kips Bay 15", "slug": "amc-kips-bay-15",
     "neighborhood": "Kips Bay", "first_run": True, "slug_confirmed": True},
    {"chain": "amc", "name": "AMC 19th St. East 6", "slug": "amc-19th-st-east-6",
     "neighborhood": "Flatiron", "first_run": True, "slug_confirmed": True},
    {"chain": "amc", "name": "AMC Village 7", "slug": "amc-village-7",
     "neighborhood": "East Village", "first_run": True, "slug_confirmed": True},
    {"chain": "amc", "name": "AMC 84th Street 6", "slug": "amc-84th-street-6",
     "neighborhood": "Upper West Side", "first_run": True, "slug_confirmed": False,
     "note": "borderline: on the 83rd-84th block, at/just below the 84th St cutoff"},

    # --- Regal (chain adapter: regal.py, TODO — browser-only, anti-bot) ----
    {"chain": "regal", "name": "Regal Times Square 4DX & RPX", "first_run": True,
     "neighborhood": "Times Square", "url": None},  # fka E-Walk; slug TBD
    {"chain": "regal", "name": "Regal Union Square 14", "first_run": True,
     "neighborhood": "Union Square", "url": None},
    {"chain": "regal", "name": "Regal Essex Crossing & RPX", "first_run": True,
     "neighborhood": "Lower East Side",
     "url": "https://www.regmovies.com/theatres/regal-essex-crossing-1412"},  # CONFIRMED
    {"chain": "regal", "name": "Regal Battery Park 11", "first_run": True,
     "neighborhood": "Battery Park City",
     "url": "https://www.regmovies.com/theatres/regal-battery-park-1335"},  # CONFIRMED

    # --- Bespoke ticketing (own adapter or vision fallback) ----------------
    {"chain": "alamo", "name": "Alamo Drafthouse Lower Manhattan", "first_run": True,
     "neighborhood": "Financial District",
     "url": "https://drafthouse.com/nyc/theater/lower-manhattan"},
    {"chain": "other", "name": "The Cinemas at Fulton Market", "first_run": True,
     "neighborhood": "Seaport", "note": "fka iPic; bought by Blue Fox 2026, no dining"},

    # --- Arthouse / independent (first_run=False: won't screen The Odyssey) -
    {"chain": "indie", "name": "New Plaza Cinema", "first_run": False},
    {"chain": "indie", "name": "Film at Lincoln Center", "first_run": False},
    {"chain": "indie", "name": "Paris Theater (Netflix)", "first_run": False},
    {"chain": "indie", "name": "Cinema 123 by Angelika", "first_run": False},
    {"chain": "indie", "name": "Film at MoMA", "first_run": False},
    {"chain": "indie", "name": "Quad Cinema", "first_run": False},
    {"chain": "indie", "name": "Cinema Village", "first_run": False},
    {"chain": "indie", "name": "Village East by Angelika", "first_run": False},
    {"chain": "indie", "name": "IFC Center", "first_run": False},
    {"chain": "indie", "name": "Angelika Film Center & Café", "first_run": False},
    {"chain": "indie", "name": "Film Forum", "first_run": False},
    {"chain": "indie", "name": "Anthology Film Archives", "first_run": False},
    {"chain": "indie", "name": "Roxy Cinema", "first_run": False},
    {"chain": "indie", "name": "Firehouse: DCTV's Documentary Cinema", "first_run": False},
    {"chain": "indie", "name": "Metrograph", "first_run": False},
]


def for_chain(chain: str, first_run_only: bool = True) -> list[dict]:
    return [v for v in VENUES
            if v["chain"] == chain and (v.get("first_run") or not first_run_only)]


def odyssey_targets() -> list[dict]:
    """Venues that plausibly screen a wide release (AMC + Regal + bespoke multiplexes)."""
    return [v for v in VENUES if v.get("first_run")]


if __name__ == "__main__":
    print(f"{len(VENUES)} venues; {len(odyssey_targets())} first-run (Odyssey candidates)")
    for c in ("amc", "regal", "alamo", "other", "indie"):
        vs = [v["name"] for v in VENUES if v["chain"] == c]
        print(f"  {c:6} ({len(vs)}): {', '.join(vs)}")
