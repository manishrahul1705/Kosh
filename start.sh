#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export APP_ENV=development
export SCHEDULER_ENABLED=false AUTO_MIGRATE=false COLLECT_ON_STARTUP=false STARTUP_RECOVERY_ENABLED=false
export DEV_LOGIN_ENABLED=true KOSH_AUTO_BOOTSTRAP=true KOSH_AS_OF_DATE=2026-10-13 VITE_DEV_LOGIN=true
python_bin="${KOSH_PYTHON:-.venv/bin/python}"
if [[ ! -x "$python_bin" ]]; then python_bin=python3; fi
"$python_bin" -m uvicorn app.main:app --host 127.0.0.1 --port 8010 &
api_pid=$!
(cd frontend && exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5180 --strictPort) &
web_pid=$!
cleanup() { kill "$api_pid" "$web_pid" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
echo "Preparing the business workspace. The first start may take a few minutes."
ready=false
while kill -0 "$api_pid" 2>/dev/null && kill -0 "$web_pid" 2>/dev/null; do
  if [[ "$ready" == false ]] && "$python_bin" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/health', timeout=2)" >/dev/null 2>&1; then
    echo "Open http://127.0.0.1:5180/login — click Sign in."
    ready=true
  fi
  sleep 1
done
exit 1
