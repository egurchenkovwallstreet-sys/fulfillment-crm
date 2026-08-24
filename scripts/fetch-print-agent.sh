#!/bin/bash
# Скачивает последний .exe агента печати в frontend/public/downloads/
set -euo pipefail

REPO="${PRINT_AGENT_REPO:-egurchenkovwallstreet-sys/fulfillment-crm}"
TAG="${PRINT_AGENT_TAG:-print-agent}"
FILE="FulfillmentCRM-PrintAgent.exe"
DEST="frontend/public/downloads/${FILE}"
URL="https://github.com/${REPO}/releases/download/${TAG}/${FILE}"

mkdir -p "$(dirname "$DEST")"

echo "=== fetch print agent ==="
echo "URL: $URL"
if curl -fsSL -o "${DEST}.tmp" "$URL"; then
  mv "${DEST}.tmp" "$DEST"
  ls -lh "$DEST"
  echo "OK: $DEST"
else
  rm -f "${DEST}.tmp"
  if [[ -f "$DEST" ]]; then
    echo "WARN: download failed, keeping existing $DEST"
  else
    echo "ERROR: no $DEST on disk and download failed"
    echo "Build agent in GitHub Actions or upload manually."
    exit 1
  fi
fi
