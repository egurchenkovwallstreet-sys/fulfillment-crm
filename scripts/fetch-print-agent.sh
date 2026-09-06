#!/bin/bash
# Скачивает агент печати (portable zip + onefile exe) в frontend/public/downloads/
set -euo pipefail

REPO="${PRINT_AGENT_REPO:-egurchenkovwallstreet-sys/fulfillment-crm}"
TAG="${PRINT_AGENT_TAG:-print-agent}"
BASE="frontend/public/downloads"
ZIP_NAME="FulfillmentCRM-PrintAgent-portable.zip"
EXE_NAME="FulfillmentCRM-PrintAgent-onefile.exe"
LEGACY_EXE="FulfillmentCRM-PrintAgent.exe"
ZIP_DEST="${BASE}/${ZIP_NAME}"
EXE_DEST="${BASE}/${EXE_NAME}"

mkdir -p "$BASE"

if [[ -f "$ZIP_DEST" ]] && unzip -t "$ZIP_DEST" >/dev/null 2>&1; then
  echo "=== print agent ==="
  echo "OK: zip уже на сервере — скачивание с GitHub не нужно"
  ls -lh "$ZIP_DEST"
  exit 0
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

looks_like_error_page() {
  local file="$1"
  local first
  first="$(head -c 1 "$file" 2>/dev/null || true)"
  [[ "$first" == "<" || "$first" == "{" ]]
}

validate_binary() {
  local file="$1"
  local kind="$2"

  if looks_like_error_page "$file"; then
    echo "  ERROR: response is HTML/JSON, not a binary:"
    head -c 240 "$file" || true
    echo
    return 1
  fi

  case "$kind" in
    zip)
      if ! head -c 2 "$file" | od -An -tx1 | grep -qi '50  4b'; then
        echo "  ERROR: bad zip magic bytes"
        return 1
      fi
      if ! unzip -t "$file" >/dev/null 2>&1; then
        echo "  ERROR: unzip test failed"
        return 1
      fi
      ;;
    exe)
      if ! head -c 2 "$file" | od -An -tx1 | grep -qi '4d  5a'; then
        echo "  ERROR: bad exe MZ header"
        return 1
      fi
      ;;
  esac
  return 0
}

download_public_url() {
  local file="$1"
  local dest="$2"
  local url="https://github.com/${REPO}/releases/download/${TAG}/${file}"
  local tmp="${dest}.tmp"

  echo "  GET (public) $url"
  if ! curl -fsSL -o "$tmp" "$url"; then
    rm -f "$tmp"
    return 1
  fi
  mv "$tmp" "$dest"
  return 0
}

github_asset_id() {
  local file="$1"
  python3 - "$REPO" "$TAG" "$file" <<'PY'
import json
import sys
import urllib.request

repo, tag, name = sys.argv[1:4]
token = __import__("os").environ.get("GITHUB_TOKEN", "")
req = urllib.request.Request(
    f"https://api.github.com/repos/{repo}/releases/tags/{tag}",
    headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "fulfillment-crm-deploy",
    },
)
with urllib.request.urlopen(req, timeout=60) as resp:
    data = json.load(resp)
for asset in data.get("assets", []):
    if asset.get("name") == name:
        print(asset["id"])
        break
PY
}

download_github_api() {
  local file="$1"
  local dest="$2"
  local kind="$3"
  local tmp="${dest}.tmp"
  local asset_id

  if [[ -z "${GITHUB_TOKEN:-}" ]]; then
    echo "  SKIP API: GITHUB_TOKEN not set"
    return 1
  fi

  asset_id="$(github_asset_id "$file" || true)"
  if [[ -z "$asset_id" ]]; then
    echo "  ERROR: asset not found in release tag=${TAG}: $file"
    return 1
  fi

  echo "  GET (api) repos/${REPO}/releases/assets/${asset_id} -> $file"
  if ! curl -fsSL \
    -H "Accept: application/octet-stream" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "User-Agent: fulfillment-crm-deploy" \
    -o "$tmp" \
    "https://api.github.com/repos/${REPO}/releases/assets/${asset_id}"; then
    rm -f "$tmp"
    return 1
  fi

  if ! validate_binary "$tmp" "$kind"; then
    rm -f "$tmp"
    return 1
  fi

  mv "$tmp" "$dest"
  ls -lh "$dest"
  return 0
}

fetch_asset() {
  local file="$1"
  local dest="$2"
  local kind="$3"

  echo "=== fetch $file ==="

  if download_github_api "$file" "$dest" "$kind"; then
    return 0
  fi

  local tmp="${dest}.tmp"
  rm -f "$tmp"
  if download_public_url "$file" "$dest"; then
    if validate_binary "$dest" "$kind"; then
      ls -lh "$dest"
      return 0
    fi
    rm -f "$dest"
  fi

  return 1
}

echo "=== fetch print agent ==="
echo "Release: https://github.com/${REPO}/releases/tag/${TAG}"
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  echo "Auth: GITHUB_TOKEN set"
else
  echo "Auth: no GITHUB_TOKEN (private repo will fail — add to .env)"
fi

zip_ok=0
exe_ok=0

if fetch_asset "$ZIP_NAME" "$ZIP_DEST" zip; then
  zip_ok=1
fi

if fetch_asset "$EXE_NAME" "$EXE_DEST" exe; then
  exe_ok=1
elif fetch_asset "$LEGACY_EXE" "$EXE_DEST" exe; then
  echo "WARN: using legacy release asset $LEGACY_EXE as onefile"
  exe_ok=1
fi

if [[ "$zip_ok" -ne 1 ]]; then
  if [[ -f "$ZIP_DEST" ]] && unzip -t "$ZIP_DEST" >/dev/null 2>&1; then
    echo "WARN: keeping existing $ZIP_DEST"
    zip_ok=1
  fi
fi

if [[ "$zip_ok" -ne 1 ]]; then
  echo
  echo "ERROR: $ZIP_NAME missing or corrupt."
  echo
  echo "Private GitHub repo — на сервере в /opt/fulfillment-crm/.env добавьте:"
  echo "  GITHUB_TOKEN=ghp_xxxxxxxx"
  echo "Токен: GitHub → Settings → Developer settings → PAT → scope repo (read)."
  echo
  echo "Или один раз положите zip вручную (без токена):"
  echo "  $ZIP_DEST"
  echo "  Скачать: https://github.com/${REPO}/releases/tag/${TAG}"
  echo "  Файл: $ZIP_NAME"
  echo "  Потом снова: bash scripts/deploy.sh"
  exit 1
fi

echo "=== print agent fetch done (zip=$zip_ok exe=$exe_ok) ==="
