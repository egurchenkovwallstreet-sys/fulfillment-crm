"""Совместимость и диагностика агента на старых ПК Windows."""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

AGENT_VERSION = "1.2.0"

APP_NAME = "FulfillmentCRM"
AGENT_NAME = "PrintAgent"


def bootstrap_log(message: str) -> None:
  """Пишет в лог до полной инициализации (если exe падает при старте)."""
  line = f"{message}\n"
  try:
    base = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME / AGENT_NAME
    base.mkdir(parents=True, exist_ok=True)
    with (base / "agent.log").open("a", encoding="utf-8") as handle:
      handle.write(line)
  except OSError:
    pass
  try:
    temp_log = Path(os.environ.get("TEMP", ".")) / "FulfillmentCRM-PrintAgent-bootstrap.log"
    with temp_log.open("a", encoding="utf-8") as handle:
      handle.write(line)
  except OSError:
    pass


def is_frozen() -> bool:
  return bool(getattr(sys, "frozen", False))


def has_vc_runtime() -> bool:
  if sys.platform != "win32":
    return True
  import ctypes

  for name in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"):
    try:
      ctypes.WinDLL(name)
    except OSError:
      return False
  return True


def windows_version_label() -> str:
  if sys.platform != "win32":
    return sys.platform
  try:
    ver = platform.win32_ver()
    return " ".join(part for part in (ver[0], ver[1], ver[2]) if part)
  except Exception:
    return platform.platform()


def collect_startup_info() -> dict:
  return {
    "agent_version": AGENT_VERSION,
    "python": platform.python_version(),
    "platform": platform.platform(),
    "windows": windows_version_label(),
    "frozen": is_frozen(),
    "arch": platform.machine(),
    "vc_runtime": has_vc_runtime(),
  }


def show_error(title: str, message: str) -> None:
  bootstrap_log(f"ERROR dialog: {title} | {message}")
  if sys.platform != "win32":
    print(f"{title}\n{message}")
    return
  try:
    import ctypes

    ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
  except Exception:
    print(f"{title}\n{message}")


def ensure_runtime_or_exit() -> None:
  if sys.platform != "win32":
    show_error(
      "Fulfillment CRM — Агент печати",
      "Агент печати поддерживается только на Windows.",
    )
    raise SystemExit(1)

  info = collect_startup_info()
  bootstrap_log(
    "=== bootstrap === "
    + f"v={info['agent_version']} py={info['python']} win={info['windows']} "
    + f"arch={info['arch']} frozen={info['frozen']} vc={info['vc_runtime']}"
  )

  if not info["vc_runtime"]:
    show_error(
      "Fulfillment CRM — не хватает компонентов Windows",
      (
        "Не найден Microsoft Visual C++ Redistributable 2015–2022 (x64).\n\n"
        "1. Скачайте и установите:\n"
        "   https://aka.ms/vs/17/release/vc_redist.x64.exe\n"
        "2. Перезагрузите ПК\n"
        "3. Запустите агент снова\n\n"
        f"Журнал: {os.environ.get('APPDATA', '')}\\FulfillmentCRM\\PrintAgent\\agent.log"
      ),
    )
    raise SystemExit(2)
