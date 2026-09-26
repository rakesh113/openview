#!/usr/bin/env bash
# API on :8000 and the Vite dev server on :5173.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m uvicorn openview.main:create_app --factory --host 0.0.0.0 --port 8000 &
api_pid=$!
trap 'kill $api_pid' EXIT
cd frontend
npm run dev
