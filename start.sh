#!/usr/bin/env bash
# ParseProof - sets itself up on first run, then starts the server at http://127.0.0.1:8010
set -e
cd "$(dirname "$0")"

if [ ! -x venv/bin/python ]; then
  echo "Setting up Python packages. This happens once and takes a few minutes..."
  python3 -m venv venv
  venv/bin/python -m pip install --upgrade pip
  venv/bin/python -m pip install -r requirements.txt
fi

if [ ! -f web/dist/index.html ]; then
  echo "Building the web app. This happens once..."
  (cd web && npm install --no-audit --no-fund && npm run build)
fi

[ -f .env ] || cp .env.example .env

echo "Open http://127.0.0.1:8010 in your browser"
exec venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8010
