"""Точка входа агента печати Fulfillment CRM (Windows, трей + HTTP API)."""
from __future__ import annotations

import json
import os
import sys
import threading
import webbrowser
from pathlib import Path

from paths import get_config_path, get_data_dir, get_example_config_path, is_frozen

if not is_frozen():
  ROOT = Path(__file__).resolve().parent
  if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
  import win32event
  import win32api
  import winerror

  HAS_WIN32 = True
except ImportError:
  HAS_WIN32 = False

AGENT_MUTEX = "Global\\FulfillmentCRM_PrintAgent_v1"
AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE = "FulfillmentCRM PrintAgent"


def ensure_config() -> None:
  path = get_config_path()
  if path.exists():
    return
  example = get_example_config_path()
  if example.exists():
    path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    return
  path.write_text(
    json.dumps(
      {
        "host": "127.0.0.1",
        "port": 9123,
        "default_printer": "",
        "jobs": {
          "fbs_sticker": {"width_mm": 58, "height_mm": 40},
          "supply_sticker": {"width_mm": 58, "height_mm": 40},
          "cell_label": {"width_mm": 75, "height_mm": 120},
        },
      },
      ensure_ascii=False,
      indent=2,
    ),
    encoding="utf-8",
  )


def acquire_single_instance() -> bool:
  if not HAS_WIN32:
    return True
  try:
    handle = win32event.CreateMutex(None, False, AGENT_MUTEX)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
      return False
    return True
  except Exception:
    return True


def exe_path() -> str:
  if is_frozen():
    return sys.executable
  return str(Path(__file__).resolve().parent / "agent_main.py")


def autostart_enabled() -> bool:
  if not HAS_WIN32:
    return False
  try:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as key:
      value, _ = winreg.QueryValueEx(key, AUTOSTART_VALUE)
      return bool(value)
  except OSError:
    return False


def set_autostart(enabled: bool) -> None:
  if not HAS_WIN32:
    return
  import winreg

  with winreg.OpenKey(
    winreg.HKEY_CURRENT_USER,
    AUTOSTART_KEY,
    0,
    winreg.KEY_SET_VALUE,
  ) as key:
    if enabled:
      command = f'"{exe_path()}"'
      winreg.SetValueEx(key, AUTOSTART_VALUE, 0, winreg.REG_SZ, command)
    else:
      try:
        winreg.DeleteValue(key, AUTOSTART_VALUE)
      except OSError:
        pass


def start_server_thread() -> threading.Thread:
  from server import run_server

  cfg = json.loads(get_config_path().read_text(encoding="utf-8"))
  host = cfg.get("host", "127.0.0.1")
  port = int(cfg.get("port", 9123))

  thread = threading.Thread(target=run_server, args=(host, port), daemon=True, name="print-api")
  thread.start()
  return thread


def health_url() -> str:
  cfg = json.loads(get_config_path().read_text(encoding="utf-8"))
  port = int(cfg.get("port", 9123))
  return f"http://127.0.0.1:{port}/health"


def open_config_folder(_icon=None, _item=None) -> None:
  os.startfile(str(get_data_dir()))


def open_health(_icon=None, _item=None) -> None:
  webbrowser.open(health_url())


def toggle_autostart(_icon=None, item=None) -> None:
  set_autostart(not item.checked)


def quit_agent(icon, _item=None) -> None:
  icon.visible = False
  icon.stop()
  os._exit(0)


def run_tray() -> None:
  from PIL import Image, ImageDraw, ImageFont
  import pystray

  size = 64
  img = Image.new("RGB", (size, size), "#2563eb")
  draw = ImageDraw.Draw(img)
  try:
    font = ImageFont.truetype("arial.ttf", 22)
  except OSError:
    font = ImageFont.load_default()
  draw.text((14, 18), "FF", fill="white", font=font)

  cfg = json.loads(get_config_path().read_text(encoding="utf-8"))
  port = int(cfg.get("port", 9123))

  icon = pystray.Icon(
    "FulfillmentCRM PrintAgent",
    img,
    f"Fulfillment CRM — Агент печати (: {port})",
    menu=pystray.Menu(
      pystray.MenuItem("Проверка (health)", open_health, default=True),
      pystray.MenuItem("Папка настроек", open_config_folder),
      pystray.MenuItem(
        "Автозапуск Windows",
        toggle_autostart,
        checked=lambda _item: autostart_enabled(),
      ),
      pystray.Menu.SEPARATOR,
      pystray.MenuItem("Выход", quit_agent),
    ),
  )
  icon.run()


def main() -> int:
  if sys.platform != "win32":
    print("Агент печати поддерживается только на Windows.")
    return 1

  if not acquire_single_instance():
    import ctypes

    ctypes.windll.user32.MessageBoxW(
      0,
      "Агент печати Fulfillment CRM уже запущен.",
      "Fulfillment CRM",
      0x40,
    )
    return 0

  ensure_config()
  start_server_thread()

  if is_frozen() or "--tray" in sys.argv:
    run_tray()
    return 0

  from server import main as server_main

  server_main()
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
