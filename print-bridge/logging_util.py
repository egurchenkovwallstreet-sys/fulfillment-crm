"""Лог агента печати в AppData (для диагностики падений)."""
from __future__ import annotations

import traceback
from datetime import datetime

from paths import get_data_dir


def log_path():
  return get_data_dir() / "agent.log"


def log(message: str) -> None:
  line = f"{datetime.now().isoformat(timespec='seconds')} {message}\n"
  try:
    with log_path().open("a", encoding="utf-8") as handle:
      handle.write(line)
  except OSError:
    pass


def log_exception(context: str) -> None:
  log(f"ERROR {context}\n{traceback.format_exc()}")
