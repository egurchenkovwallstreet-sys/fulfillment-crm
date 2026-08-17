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

echo "Applying migrations..."
python manage.py migrate --noinput --fake-initial

echo "Seeding warehouse cells..."
python manage.py seed_cells || true

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting application..."
exec "$@"
