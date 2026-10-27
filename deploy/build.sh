#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python -m pip install -r backend/requirements.lock.txt
cd frontend
npm ci --include=dev
npm run build
cd ../backend
python ../deploy/check_runtime.py
