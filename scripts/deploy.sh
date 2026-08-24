#!/bin/bash
set -euo pipefail
cd /opt/fulfillment-crm

echo "=== git ==="
git fetch origin main
git reset --hard origin/main
git log -1 --oneline

echo "=== build ==="
docker compose build --no-cache frontend web worker

echo "=== up db/redis ==="
docker compose up -d db redis

echo "=== up web (migrations + gunicorn) ==="
docker compose up -d web

echo "=== wait for backend health ==="
ok=0
for i in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8001/api/health/ >/dev/null 2>&1; then
    ok=1
    break
  fi
  echo "  attempt $i/60..."
  if [[ "$i" -eq 6 || "$i" -eq 12 || "$i" -eq 24 ]]; then
    docker compose logs web --tail 15 2>/dev/null || true
  fi
  sleep 5
done
if [[ "$ok" -ne 1 ]]; then
  echo "ERROR: backend did not become healthy in time"
  docker compose ps
  docker compose logs web --tail 80
  exit 1
fi

echo "=== up worker + frontend ==="
docker compose up -d --force-recreate worker frontend

echo "=== frontend bundle check ==="
if docker compose exec -T frontend sh -c 'grep -rq "Поиск по баркоду" /usr/share/nginx/html/assets/ 2>/dev/null'; then
  echo "OK: новый фронтенд (поиск по баркоду в бандле)"
else
  echo "WARN: в контейнере frontend старый бандл — проверьте docker compose build frontend"
fi

echo "=== backend version ==="
curl -fsS http://127.0.0.1:8001/api/health/
echo

echo "=== frontend ==="
curl -fsS -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8080/ || true

echo "=== done ==="
docker compose ps
