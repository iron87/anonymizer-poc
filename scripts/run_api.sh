#!/usr/bin/env bash
set -euo pipefail

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-9000}"

uvicorn src.api.main:app --host "$HOST" --port "$PORT" --reload
