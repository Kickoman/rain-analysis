#!/usr/bin/env bash
# Routine backend update: pull, rebuild if dependencies changed, migrate,
# restart. Run from anywhere; operates on the repo this script lives in.
# Requires the invoking user to be able to run docker (docker group or sudo).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -f "$REPO_DIR/deploy/docker-compose.yml")

cd "$REPO_DIR"
git pull --ff-only

"${COMPOSE[@]}" build
"${COMPOSE[@]}" run --rm backend python -m alembic upgrade head
"${COMPOSE[@]}" up -d

sleep 2
BACKEND_PORT="${BACKEND_PORT:-7010}"
curl -sf "http://127.0.0.1:${BACKEND_PORT}/health" && echo && echo "OK: backend is up"
