"""Пути данных агента печати (dev и собранный .exe)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "FulfillmentCRM"
AGENT_NAME = "PrintAgent"


def is_frozen() -> bool:
  return bool(getattr(sys, "frozen", False))


def get_data_dir() -> Path:
  if is_frozen():
    base = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME / AGENT_NAME
  else:
    base = Path(__file__).resolve().parent
  base.mkdir(parents=True, exist_ok=True)
  return base


def get_config_path() -> Path:
  return get_data_dir() / "config.json"


def get_example_config_path() -> Path:
  if is_frozen():
    return Path(sys._MEIPASS) / "config.example.json"  # type: ignore[attr-defined]
  return Path(__file__).resolve().parent / "config.example.json"
