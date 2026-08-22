#!/bin/bash
set -e

echo "Waiting for database..."
python - <<'PY'
import os
import sys
import time

import psycopg2

url = os.environ.get("DATABASE_URL", "")
# postgres:// -> postgresql:// for psycopg2 URI parsing
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql://", 1)

# Simple parse: postgresql://user:pass@host:port/db
from urllib.parse import urlparse

parsed = urlparse(url)
host = parsed.hostname or "db"
port = parsed.port or 5432
user = parsed.username or "fulfillment"
password = parsed.password or "fulfillment"
dbname = parsed.path.lstrip("/") or "fulfillment"

for i in range(30):
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=dbname,
        )
        conn.close()
        print("Database is ready.")
        break
    except psycopg2.OperationalError:
        if i == 29:
            print("Database not available.", file=sys.stderr)
            sys.exit(1)
        time.sleep(2)
PY

# Миграции только в web — worker/beat параллельно ломали sellers.0003 (duplicate sequence).
if [[ "$1" == "celery" ]]; then
  echo "Starting Celery..."
  exec "$@"
fi

echo "Applying migrations..."
if ! python manage.py migrate --noinput --fake-initial; then
  echo "Migration failed. Check: docker compose exec web python manage.py showmigrations"
  exit 1
fi

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting application..."
exec "$@"
