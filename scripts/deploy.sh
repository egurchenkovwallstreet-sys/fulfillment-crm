#!/bin/bash
set -euo pipefail
cd /opt/fulfillment-crm

echo "=== git ==="
git fetch origin main
git reset --hard origin/main
git log -1 --oneline
git rev-parse --short HEAD > backend/BUILD_VERSION
echo "BUILD_VERSION=$(cat backend/BUILD_VERSION)"

echo "=== build ==="
# Без --no-cache: базовые образы (node/python) берутся из кэша и не упираются в лимит Docker Hub (429).
if [[ "${FULL_REBUILD:-0}" == "1" ]]; then
  docker compose build --no-cache frontend web worker
else
  docker compose build frontend web worker
fi

echo "=== up db/redis ==="
docker compose up -d db redis

echo "=== up web (migrations + gunicorn) ==="
docker compose up -d --force-recreate web beat

echo "=== wait for backend health ==="
EXPECTED_BUILD="$(cat backend/BUILD_VERSION)"
ok=0
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:8001/api/health/" 2>/dev/null | grep -q "\"build\":\"${EXPECTED_BUILD}\""; then
    ok=1
    break
  fi
  if curl -fsS http://127.0.0.1:8001/api/health/ >/dev/null 2>&1; then
    echo "  WARN: backend отвечает, но build != ${EXPECTED_BUILD} (ещё старый контейнер?)"
  fi
  echo "  attempt $i/60..."
  if [[ "$i" -eq 6 || "$i" -eq 12 || "$i" -eq 24 ]]; then
    docker compose logs web --tail 15 2>/dev/null || true
  fi
  sleep 5
done
if [[ "$ok" -ne 1 ]]; then
  echo "ERROR: backend не поднялся с build=${EXPECTED_BUILD}"
  docker compose ps
  docker compose logs web --tail 80
  exit 1
fi
echo "OK: backend build=${EXPECTED_BUILD}"

echo "=== storage snapshots + accruals ==="
if docker compose exec -T web python manage.py rebuild_storage_daily_quantities; then
  echo "OK: storage snapshots and accruals"
else
  echo "WARN: rebuild_storage_daily_quantities failed — run manually on server"
fi

echo "=== up worker + frontend ==="
docker compose up -d --force-recreate worker frontend

echo "=== frontend bundle check ==="
if docker compose exec -T frontend sh -c 'grep -rq "Удалённые из сборки" /usr/share/nginx/html/assets/ 2>/dev/null'; then
  echo "OK: фронтенд — восстановление скрытых заказов на сборке"
elif docker compose exec -T frontend sh -c 'grep -rq "Передать на сборку" /usr/share/nginx/html/assets/ 2>/dev/null'; then
  echo "OK: новый фронтенд (сборка FBS — одна кнопка)"
elif docker compose exec -T frontend sh -c 'grep -rq "Поиск по баркоду" /usr/share/nginx/html/assets/ 2>/dev/null'; then
  echo "WARN: фронтенд частично обновлён (ячейки), но сборка FBS — старая версия"
else
  echo "WARN: в контейнере frontend старый бандл — проверьте docker compose build frontend"
fi

echo "=== backend version (8001 и через nginx 8080) ==="
curl -fsS http://127.0.0.1:8001/api/health/
echo
curl -fsS http://127.0.0.1:8080/api/health/ || echo "WARN: nginx 8080 /api/health недоступен"
echo

echo "=== frontend downloads ==="
curl -fsS -o /dev/null -w "zip HTTP %{http_code} size %{size_download}\n" http://127.0.0.1:8080/downloads/FulfillmentCRM-PrintAgent-portable.zip || true
curl -fsS -o /dev/null -w "bat HTTP %{http_code}\n" http://127.0.0.1:8080/downloads/install-agent.bat || true

echo "=== print agent (после деплоя CRM, не блокирует обновление) ==="
if timeout 180 bash scripts/fetch-print-agent.sh; then
  echo "OK: print agent"
else
  echo "WARN: print agent fetch skipped/failed — CRM уже обновлён, zip обычно приходит из git"
fi
ls -lh frontend/public/downloads/FulfillmentCRM-PrintAgent-portable.zip 2>/dev/null || true

echo "=== done ==="
docker compose ps
