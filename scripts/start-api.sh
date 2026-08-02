#!/usr/bin/env bash
# Start the concept-book FastAPI backend.
# Must be run inside the spl123 conda env (so spl3 is on PATH).
#
# One-time setup:
#   conda activate spl123
#   pip install -r requirements-api.txt
#
# Then start:
#   conda activate spl123
#   bash scripts/start-api.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
API_PORT="$(grep -m1 '^API_PORT=' "$REPO/.env" 2>/dev/null | cut -d= -f2)"
API_PORT="${API_PORT:-8200}"
uvicorn api.app:app --host 0.0.0.0 --port "$API_PORT" --reload
