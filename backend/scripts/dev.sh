#!/usr/bin/env bash
# Starts all four processes. Ctrl-C stops them together.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=./.venv/bin/python

# Postgres and Redis come from docker compose; a sqlite+aiosqlite DATABASE_URL
# skips this check and runs with no Docker at all.
if [[ "${DATABASE_URL:-}" != sqlite* ]]; then
  if ! docker compose ps --status running 2>/dev/null | grep -q postgres; then
    echo "Postgres is not running. Start it with:  docker compose up -d" >&2
    exit 1
  fi
fi

echo "Relay backend — API :8000 · scheduler · worker · notifier"
$PY -m uvicorn app.main:app --reload --port 8000 &
API=$!
$PY -m app.scheduler.ticker &
TICK=$!
$PY -m app.runtime.worker &
WORK=$!
$PY -m app.notify.dispatcher &
NOTE=$!

trap 'kill $API $TICK $WORK $NOTE 2>/dev/null || true' INT TERM EXIT
wait
