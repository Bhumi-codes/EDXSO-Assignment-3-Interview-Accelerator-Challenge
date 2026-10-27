#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ -d ../backend ]; then
  cd ../backend
fi
if [ "${RUN_MIGRATIONS_ON_START:-false}" = "true" ]; then
  python -m alembic upgrade head
fi
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 --proxy-headers --forwarded-allow-ips '*' --timeout-graceful-shutdown 120
