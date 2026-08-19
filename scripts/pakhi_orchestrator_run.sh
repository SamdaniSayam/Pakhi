#!/usr/bin/env bash
#
# pakhi_orchestrator_run.sh — daily WS-2 paper-trading execution.
#
# Steps:
#   1. Load environment (.env files) so the Postgres URL is available.
#   2. Refresh the OJ market feed (prevents the OJ-staleness armor from
#      rejecting the cycle 7+ days after the last close).
#   3. Rebuild the back-adjusted continuous OJ series from the refreshed raw.
#   4. Run the WS-2 T3 orchestrator against Postgres (writes ledger + NOTIFY).
#
# Intended to be ExecStart'd by pakhi-orchestrator.service, triggered daily
# by pakhi-orchestrator.timer. journalctl captures all stdout/stderr.
set -euo pipefail

REPO=/home/megalith/Desktop/pakhi
PRIVATE=/home/megalith/Desktop/Pakhi-private
PY=/home/megalith/miniconda/bin/python

cd "$REPO"

# Load environment tolerantly (handles spaces around '=' in .env).
# Prefer Supabase write URL for the paper ledger; fall back to read URL.
set -a
for f in "$REPO/.env" "$PRIVATE/.env"; do
  [ -f "$f" ] || continue
  # shellcheck disable=SC1090
  source <(grep -v '^[[:space:]]*#' "$f" | sed -E 's/^[[:space:]]*//; s/[[:space:]]*=[[:space:]]*/=/; s/[[:space:]]*$//' | grep '=')
done
set +a

DB_URL_RESOLVED="${PAKHI_DB_WRITE_URL:-${PAKHI_DB_READ_URL}}"
if [ -z "${DB_URL_RESOLVED:-}" ]; then
  echo "ERROR: no Postgres URL found (PAKHI_DB_WRITE_URL/PAKHI_DB_READ_URL)" >&2
  exit 1
fi

echo "[$(date -u)] refreshing OJ market data"
"$PY" "$REPO/scripts/refresh_oj.py"

echo "[$(date -u)] rebuilding continuous OJ series"
"$PY" "$REPO/scripts/build_continuous.py"

echo "[$(date -u)] running WS-2 T3 orchestrator against Postgres"
"$PY" "$REPO/scripts/run_ws2_t3_orchestrate.py" --db "$DB_URL_RESOLVED"

echo "[$(date -u)] done"
