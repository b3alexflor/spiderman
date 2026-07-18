#!/usr/bin/env bash
# One-command setup + launch. Clone the repo, run ./run.sh, open the URL.
#
# The site serves IMMEDIATELY on the bundled sample (re-dated to today), while a
# LIVE ingest runs in the background — first launch also downloads Chromium for
# Playwright. The moment real data lands, the demo rows are pruned and the page
# shows live seats on refresh (WAL: the API reads fresh data, no restart).
#
# Ingest is TWO-STAGE so the site is useful fast: stage 1 grabs the flagship
# venue + Regal for TODAY (~1-2 min); stage 2 fills all venues / all days behind
# it (throttled, takes a while — nobody is waiting on it).
#
#   ./run.sh [port]                 # serve + staged live refresh in the background
#   NO_INGEST=1 ./run.sh            # demo data only (offline / no scraping)
#   INGEST_INTERVAL=1800 ./run.sh   # stage 2 keeps refreshing every 30 min (daemon)
#   INGEST_FAST_ARGS="…" ./run.sh   # override stage 1 scope
#   INGEST_ARGS="…" ./run.sh        # override stage 2 scope
set -euo pipefail
cd "$(dirname "$0")"
PORT="${1:-8000}"

# 0. pick a Python >= 3.10 (the code uses modern union syntax; macOS's
#    CommandLineTools python3 is 3.9 and will crash on import)
pick_python() {
  for c in "${PYTHON:-}" python3.13 python3.12 python3.11 python3.10 python3; do
    [ -n "$c" ] && command -v "$c" >/dev/null 2>&1 &&
      "$c" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' 2>/dev/null &&
      { echo "$c"; return; }
  done
  return 1
}
PY="$(pick_python)" || { echo "[run] error: need Python >= 3.10 (brew install python3)"; exit 1; }

# 1. venv + deps — recreate the venv if it was built with a too-old interpreter
if [ -d .venv ] && ! .venv/bin/python -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' 2>/dev/null; then
  echo "[run] .venv uses Python < 3.10 — recreating…"
  rm -rf .venv
fi
if [ ! -d .venv ]; then
  echo "[run] creating .venv with $PY…"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "[run] installing dependencies…"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# 2. seed the DB from the bundled sample so the site has data INSTANTLY
#    (re-dated to today; auto-pruned once live data arrives)
echo "[run] seeding seats.db from samples/…"
python scripts/seed_demo.py

# 3. live ingest in the background (unless NO_INGEST=1) — logs to ingest.log
INGEST_PID=""
if [ -z "${NO_INGEST:-}" ]; then
  MODE="--once"
  [ -n "${INGEST_INTERVAL:-}" ] && MODE="--interval ${INGEST_INTERVAL}"
  # Stage 1: flagship venue (Lincoln Square) + Regal, TODAY — live data in ~1-2 min.
  SCOPE_FAST="${INGEST_FAST_ARGS:---days 1 --per-venue 3 --regal all}"
  # Stage 2: everything, politely — skips whatever stage 1 already snapshotted.
  SCOPE_FULL="${INGEST_ARGS:---all-amc --days 3 --per-venue 4 --regal all}"
  (
    echo "=== $(date '+%F %T') ingest launch — stage 1: $SCOPE_FAST | stage 2: $MODE $SCOPE_FULL"
    python -m playwright install chromium   # no-op if already installed
    # shellcheck disable=SC2086
    python scripts/ingest.py --once $SCOPE_FAST
    echo "=== $(date '+%F %T') stage 1 done — starting stage 2"
    # shellcheck disable=SC2086
    exec python scripts/ingest.py $MODE $SCOPE_FULL
  ) >>ingest.log 2>&1 &
  INGEST_PID=$!
  echo "[run] staged live ingest running in background (pid $INGEST_PID) — follow with: tail -f ingest.log"
  echo "[run] tonight's flagship data lands in ~1-2 min; full 3-day depth keeps loading behind it"
else
  echo "[run] NO_INGEST=1 — demo data only"
fi
cleanup() { [ -n "$INGEST_PID" ] && kill "$INGEST_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# 4. serve the API + website
echo
echo "[run] starting server on http://localhost:${PORT}  (Ctrl-C to stop)"
echo "[run] site: http://localhost:${PORT}/   ·   API docs: http://localhost:${PORT}/docs"
echo "[run] SSH'd in? forward the port:  ssh -L ${PORT}:localhost:${PORT} <you>@<host>"
echo
python -m uvicorn api:app --app-dir scripts --host 127.0.0.1 --port "${PORT}" --reload
