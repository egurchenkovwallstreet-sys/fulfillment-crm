#!/bin/bash
# Скачивает агент печати (portable zip + onefile exe) в frontend/public/downloads/
set -euo pipefail

REPO="${PRINT_AGENT_REPO:-egurchenkovwallstreet-sys/fulfillment-crm}"
TAG="${PRINT_AGENT_TAG:-print-agent}"
BASE="frontend/public/downloads"
ZIP_NAME="FulfillmentCRM-PrintAgent-portable.zip"
EXE_NAME="FulfillmentCRM-PrintAgent-onefile.exe"
ZIP_DEST="${BASE}/${ZIP_NAME}"
EXE_DEST="${BASE}/${EXE_NAME}"

mkdir -p "$BASE"

download_release_asset() {
  local file="$1"
  local dest="$2"
  local url="https://github.com/${REPO}/releases/download/${TAG}/${file}"
  local tmp="${dest}.tmp"
  local curl_args=(-fsSL -o "$tmp" "$url")

  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    curl_args=(-fsSL -H "Authorization: Bearer ${GITHUB_TOKEN}" -o "$tmp" "$url")
  fi

  echo "  GET $url"
  if ! curl "${curl_args[@]}"; then
    rm -f "$tmp"
    return 1
  fi

  if head -c 1 "$tmp" | grep -q '<'; then
    echo "  ERROR: response looks like HTML (404 or private repo?) — not saving $file"
    rm -f "$tmp"
    return 1
  fi

  case "$file" in
    *.zip)
      if ! head -c 2 "$tmp" | od -An -tx1 | grep -qi '50  4b'; then
        echo "  ERROR: $file is not a zip (bad magic bytes)"
        rm -f "$tmp"
        return 1
      fi
      if ! unzip -t "$tmp" >/dev/null 2>&1; then
        echo "  ERROR: $file failed unzip test"
        rm -f "$tmp"
        return 1
      fi
      ;;
    *.exe)
      if ! head -c 2 "$tmp" | od -An -tx1 | grep -qi '4d  5a'; then
        echo "  ERROR: $file is not a Windows exe (bad MZ header)"
        rm -f "$tmp"
        return 1
      fi
      ;;
  esac

  mv "$tmp" "$dest"
  ls -lh "$dest"
  return 0
}

echo "=== fetch print agent ==="
echo "Release: https://github.com/${REPO}/releases/tag/${TAG}"

zip_ok=0
exe_ok=0

if download_release_asset "$ZIP_NAME" "$ZIP_DEST"; then
  zip_ok=1
  echo "OK: $ZIP_DEST"
else
  echo "WARN: could not download $ZIP_NAME"
fi

if download_release_asset "$EXE_NAME" "$EXE_DEST"; then
  exe_ok=1
  echo "OK: $EXE_DEST"
else
  echo "WARN: could not download $EXE_NAME (optional)"
fi

if [[ "$zip_ok" -ne 1 ]]; then
  if [[ -f "$ZIP_DEST" ]] && unzip -t "$ZIP_DEST" >/dev/null 2>&1; then
    echo "WARN: using existing $ZIP_DEST"
    zip_ok=1
  else
    echo "ERROR: $ZIP_NAME missing or corrupt."
    echo "  1. GitHub → Actions → Build Print Agent → wait for green run"
    echo "  2. Or upload zip manually to $ZIP_DEST"
    echo "  3. Private repo: export GITHUB_TOKEN for deploy"
    exit 1
  fi
fi

echo "=== print agent fetch done (zip=$zip_ok exe=$exe_ok) ==="
