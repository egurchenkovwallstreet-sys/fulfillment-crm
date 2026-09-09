"""Версия деплоя — файл BUILD_VERSION в корне backend/ пишет scripts/deploy.sh."""
from __future__ import annotations

from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_BUILD_VERSION_FILE = _BACKEND_ROOT / "BUILD_VERSION"


def read_build_version() -> str:
  try:
    if _BUILD_VERSION_FILE.is_file():
      text = _BUILD_VERSION_FILE.read_text(encoding="utf-8").strip()
      if text:
        return text
  except OSError:
    pass
  return "dev"
