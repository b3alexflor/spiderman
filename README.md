# odyssey-seats

Finds every Manhattan movie theater screening **_The Odyssey_** (70mm / IMAX /
Dolby), reads the live seat maps, and ranks the best available seats by geometry +
format — served as a small website over a JSON API.

## Preface — the point behind the joke

On its face this is a whimsical project: an over-engineered way to grab a good seat
for one movie. That's the joke, and it's meant to be. But the reason it's worth
building is the **dual use** hiding inside such an innocent-looking function.

To rank a seat for *The Odyssey* at AMC Lincoln Square, you have to solve the hard
part first: reliably driving each chain's booking flow, intercepting the seat-map
JSON, defeating the polite-scraping problems (rate floors, anti-bot fronts,
per-host serialization, screenshot/vision fallback), and normalizing it all into a
clean, append-only time series. **That groundwork is now done.** The AMC pipeline —
discovery, seat-level availability, snapshotting, storage — is built, verified live,
and chain-agnostic by construction.

Which means the exact same machinery scales trivially past one film in one borough.
Point it at every AMC in the country, on any title, on any cadence, and what falls
out is a **nationwide, seat-level, time-stamped view of theatrical demand** — live
occupancy and sell-through by showtime, auditorium, format, and market. That's raw
**market-intelligence** data (box-office nowcasting, format/premium-screen demand,
regional and release-window signal), and the collection layer is **fully
customizable** for that or any other downstream purpose. The seat-finder is the demo;
the reusable AMC-scraping substrate is the actual deliverable.

(Everything here is built as low-volume, personal-use, detect-and-back-off — see
**Politeness & rate probing** below. Naming the capability is the point; deploying it
at scale is a choice with its own legal and ethical weight, and this repo deliberately
doesn't.)

## Quick start

```bash
git clone <your-repo-url> odyssey-seats && cd odyssey-seats
./run.sh
```

`run.sh` makes a venv (Python ≥ 3.10), installs deps, seeds the DB from a
**bundled sample** (re-dated to today, so the site has data instantly), serves at
**http://localhost:8000** (API docs at `/docs`) — and kicks off a **staged live
ingest in the background** (first launch also downloads Chromium):

- **Stage 1 (~1-2 min):** Lincoln Square + Regal, today — the demo rows are pruned
  the moment the first real seat map lands, so the site is fully live fast.
- **Stage 2 (background, throttled):** all 7 AMCs × 3 days — skips whatever stage 1
  already snapshotted. The page **auto-refreshes** as data streams in (new
  showings, venues, and day tabs just appear; last-update time is stamped
  top-right). No reloading needed.

Follow progress with `tail -f ingest.log`. SSH'd into a remote box? Forward the
port: `ssh -L 8000:localhost:8000 <you>@<host>`, then open `http://localhost:8000`.

**Want a wider window (e.g. a full week)?** One knob — then let it stream:

```bash
INGEST_ARGS="--all-amc --days 7 --per-venue 4 --regal all" ./run.sh
```

The site is usable the whole time; extra days simply take longer to fill.
Rough math for patience: politeness throttles AMC to ~1 request / 15s, and a
pass costs `venues × days` discovery pages + up to `venues × days × per-venue`
seat maps — so 3 days ≈ 25-30 min of background loading, 7 days ≈ an hour-plus.
Near-term days land first (soonest showings are fetched before later ones).

Other knobs (env vars): `NO_INGEST=1` serves the demo only (offline);
`INGEST_INTERVAL=1800` keeps stage 2 refreshing every 30 min instead of one pass;
`INGEST_FAST_ARGS` overrides the stage-1 scope (default
`--days 1 --per-venue 3 --regal all`). Manual ingest, any time:

```bash
source .venv/bin/activate
python -m playwright install chromium
python scripts/ingest.py --once --all-amc --days 3 --per-venue 4 --regal all
```

Architecture: **ingest** (`ingest.py`, scrapes → `seats.db`) is decoupled from
**serve** (`api.py` + `web/`, reads the DB). WAL mode lets ingest refresh the DB
while the site keeps serving — no restart. See "Running it" below for every command.

## Idea

1. **Discover** — find all Manhattan theaters + showings/formats of the film today.
2. **Fetch seats** — grab the seat map for each showing (see strategy below).
3. **Snapshot** — record availability at a timestamp; keep a screenshot as an
   archival, ground-truth image alongside the structured data.
4. **Analyze** — score every seat and rank the best *available* ones, filterable
   by section.

## Seat-data strategy: hybrid, API-first

Ticketing seat maps are JS widgets backed by a JSON API that returns each seat as
structured data (row, number, status, type, x/y coords). We prefer that:

- **API where possible** — intercept the seat-map JSON per chain (AMC,
  Regal/Fandango, Angelika/IFC/Metrograph, etc.). Gives the section filter and
  seat coordinates for free.
- **Fall back to screenshot parsing** — when a site has no usable API, screenshot
  the seat map and extract seats from the image.

Per-chain recon handles the messy parts up front: deciding which theaters
qualify, mapping unfamiliar seat-map UIs, and picking each chain's fallback.
Polling, storage, and analysis stay deterministic.

## "Optimal" seating = geometry + format/section

Seat quality is computed, not crowd-sourced:

- **Screen geometry** — center horizontally, ~⅔ back, penalize front rows and
  extreme viewing angles. Pure math from seat x/y + screen position.
- **Format / section** — weight by section type (IMAX center, premium/recliner,
  loveseat) and format (70mm IMAX vs standard).

(Availability snapshots tell us what's *free*; geometry + section tell us what's
*good*.)

## Architecture — per-chain adapters (no aggregator)

Research finding: **no official API returns live seat availability** without gated
ecommerce approval (AMC, Fandango, Regal all confirmed). Seat maps must be pulled
by driving each site's checkout flow in a browser and intercepting the seat-map
XHR (screenshot + vision fallback where there's no clean XHR). Given that, each
chain owns **both** its discovery and its seat-fetch — no centralized discovery
layer. Adapters are independently buildable, testable, and runnable.

```
adapters/
  base.py        -- Adapter protocol: discover() -> Showing[], fetch_seats(Showing) -> Seat[]
  amc.py         -- START HERE: AMC (Lincoln Square 70mm IMAX)
  regal.py       -- Regal (regmovies.com getShowtimes JSON + checkout seat XHR)
  <indies>.py    -- Metrograph, Film Forum, Angelika, Paris (bespoke / vision fallback)
snapshot.py      -- for each adapter: discover -> fetch_seats -> DB + archival screenshot
analyze/         -- geometry + format/section seat scorer
db.py + schema   -- shared normalized Showing / Seat / availability tables
vision.py        -- shared screenshot->seats fallback helper
```

Shared across adapters: the normalized `Showing`/`Seat` schema, the DB writer, the
snapshot loop, the analyzer, and the vision fallback. Everything chain-specific
(discovery endpoint, checkout URL, seat-XHR shape) lives inside its adapter.

## Data model (append-only)

```
showings(id, theater, auditorium, format, start_time, screen_geometry)
seats(showing_id, seat_id, section, row, num, x, y, type)
availability(showing_id, seat_id, captured_at, status)   -- time series
```

## Structure

- `scripts/`   — discovery, per-chain fetchers, snapshot runner, analysis
- `notebooks/` — exploration, geometry tuning, seat-ranking analysis
- `images/`    — archival seat-map screenshots (named by showing + timestamp)

## Politeness & rate probing

We're a personal-use, low-volume scraper and treat it that way in code
([scripts/rate.py](scripts/rate.py), [scripts/probe.py](scripts/probe.py)).

- **Self-imposed floors** — no site here publishes a `Crawl-delay`, so we enforce
  a conservative per-host minimum interval (AMC 15s — raised from 8s after a
  Cloudflare challenge under load; Regal 20s), with jitter, per-host
  serialization, and hard backoff on any `429/403/503` or `Retry-After`. One
  shared Chromium serves the whole pass (browser reuse is free; request pacing
  is what the floors govern).
- **Observed:** AMC robots.txt declares no crawl-delay and disallows nothing on
  showtimes/seat/checkout for `*`. Regal's robots.txt itself **403s a plain
  fetch** — anti-bot front (Cloudflare/Akamai-style), so Regal needs a real
  browser even for discovery and gets a slower floor.
- **`probe.py` characterizes safe cadence, it does not stress-test** — reads
  robots crawl-delay, sends a hard-capped handful of spaced requests, and **stops
  on the first throttle/anti-bot signal**. Output recommends a snapshot interval
  with a safety margin. Run it from your own machine/IP, since that's what gets
  characterized.

## Notes / caveats

- **Be polite** — ticketing sites dislike scraping. Slow, low-volume,
  personal-use only. Don't hammer them.
- **Geometry needs screen position** — most seat APIs give x/y; IMAX vs standard
  auditorium geometry differs, so calibrate per auditorium.

## Status

**AMC = full pipeline** (discover → seats → rank → report → visualization), working
and verified live across venues. **Regal = discovery + deep-links only**: Regal
serves showtimes publicly but gates seat availability behind a Cloudflare Turnstile
CAPTCHA on its Vista booking backend, which we won't bypass (detect-and-back-off,
not evade). So for Regal the report emits a **link you click yourself** to pick
seats. The engine is AMC-focused by design.

## Running it

Setup (once):

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

**Best-seat report** (the main product — `scripts/report.py`):

```bash
python scripts/report.py                              # AMC Lincoln Square, IMAX 70mm, today (terminal)
python scripts/report.py --days 3 --html              # plan 3 days out, as a web page (day tabs)
python scripts/report.py --all-amc --days 3 --per-venue 4 --html   # ALL 7 AMCs × 3 days, ≤4 soonest each/day
python scripts/report.py --format IMAX_70MM,DOLBY,IMAX_LASER --top 8
python scripts/report.py --venue amc-empire-25        # a different AMC (slug from venues.py)
python scripts/report.py --section Regular            # seating-section filter
python scripts/report.py --include-accessible         # keep accessible/companion seats in ranking
python scripts/report.py --regal all --html           # + Regal deep-links (you pick those seats yourself)
python scripts/report.py --no-db --save --limit 3     # skip DB, save text report, cap total showings
```

**Full Manhattan run:** `--all-amc` fetches a seat map per showing (throttled ~15s
each), so cap it with `--per-venue N` (balanced coverage) or `--limit N` — otherwise
all venues × all formats is 100+ fetches (25+ min, and AMC's Cloudflare may start
challenging; challenged showings show as "no data" and are skipped, not fatal).
Narrow with `--format` too. `--all-amc --per-venue 4 --regal all --html` is a good
"everything, reasonably" run.

**Website + API backend** (ingest → DB → API → site; no scraping at query time):

```bash
# 1. INGEST — fill seats.db (pick one):
python scripts/seed_demo.py                                  # seed from captures (no scrape)
python scripts/ingest.py --once --all-amc --days 3 --per-venue 4 --regal all   # one real scrape
python scripts/ingest.py --interval 1800 --all-amc --days 3 --per-venue 4 --regal all  # DAEMON: refresh every 30m
# 2. SERVE — JSON API (FastAPI) + the website that consumes it:
python -m uvicorn api:app --app-dir scripts --port 8000 --reload   # site / , docs /docs
```

- **API** (`scripts/api.py`): `GET /api/meta`, `/api/showings?film&date&venue&format`,
  `/api/showings/{id}/seats`. Reads only `seats.db`. Auto docs at `/docs`.
- **Site** (`web/index.html`): a static SPA that calls the API — day tabs, format &
  time chips, venue select, best-pick stub, and a seat map loaded on click.
- Old stdlib server-rendered variant is still at `scripts/app.py` (no deps).

**Reaching it over SSH** (the server's `localhost` isn't your laptop's):
- *VS Code Remote-SSH:* just run uvicorn — open the **Ports** panel, forward `8000`,
  click the forwarded link. (Often auto-forwarded.)
- *Any terminal:* from your laptop, `ssh -L 8000:localhost:8000 <you>@<host>`,
  then open `http://localhost:8000`. (Already connected? Press `Enter` then `~C`, type
  `-L 8000:localhost:8000`.)

**Seat-map visualization** (`scripts/report_html.py`) — needs a capture JSON of one
showing's seats (`{showing, seats:[...]}`), then:

```bash
python scripts/report_html.py <capture.json> reports/seatmap.html
```

**Per-adapter tools** (discovery / recon):

```bash
python scripts/adapters/amc.py --discover             # list today's AMC Odyssey showings
python scripts/adapters/amc.py --dump                 # + save rendered showtimes HTML to recon/
python scripts/adapters/amc.py --recon                # + fetch one showing's seats (saves HTML)
python scripts/adapters/regal.py --dump               # list Regal performances (Essex) + dump
python scripts/venues.py                              # print the Manhattan venue roster
```

**Raw pipeline & ops**:

```bash
python scripts/snapshot.py --at 2026-07-17T20:00:00   # discover→fetch→DB availability snapshot
python scripts/probe.py "https://www.amctheatres.com/movie-theatres/new-york-city/amc-lincoln-square-13/showtimes"
```

Default film/date are `The Odyssey` / today; override with `--film` / `--date` on
report.py and snapshot.py.

## License

[MIT](LICENSE) — the `AS IS` warranty disclaimer and liability limitation cap the
authors' exposure **to anyone who receives this code**. That is *not* the same as
indemnity, and it does *not* cover operating the scraper: running the nationwide
capability against live ticketing sites carries its own legal weight (ToS, CFAA,
anti-bot terms) that no software license disclaims. This repo is built and licensed
as low-volume, personal-use, detect-and-back-off — see **Politeness & rate probing**.
