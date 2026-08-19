#!/bin/bash
set -euo pipefail
cd /opt/fulfillment-crm

echo "=== git ==="
git fetch origin main
git reset --hard origin/main
git log -1 --oneline

echo "=== build ==="
docker compose build --no-cache frontend web worker

echo "=== up ==="
docker compose up -d frontend web worker

echo "=== wait ==="
sleep 8

echo "=== backend version ==="
curl -fsS http://127.0.0.1:8001/api/health/ || curl -fsS http://127.0.0.1:8080/api/health/
echo

echo "=== frontend bundle ==="
curl -fsS http://127.0.0.1:8080/ | head -5

echo "=== done ==="
