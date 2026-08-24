"""Точка входа агента печати Fulfillment CRM (Windows, трей + HTTP API)."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

from logging_util import log, log_exception
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
        "print_mode": "full_page",
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
    win32event.CreateMutex(None, False, AGENT_MUTEX)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
      return False
    return True
  except Exception:
    log_exception("acquire_single_instance")
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


def read_port() -> int:
  cfg = json.loads(get_config_path().read_text(encoding="utf-8"))
  return int(cfg.get("port", 9123))


def health_url() -> str:
  return f"http://127.0.0.1:{read_port()}/health"


def wait_for_server(timeout_sec: float = 15.0) -> bool:
  import urllib.error
  import urllib.request

  deadline = time.time() + timeout_sec
  url = health_url()
  while time.time() < deadline:
    try:
      with urllib.request.urlopen(url, timeout=1.5) as response:
        if response.status == 200:
          return True
    except (urllib.error.URLError, TimeoutError, OSError):
      time.sleep(0.25)
  return False


def start_server_thread() -> threading.Thread:
  from server import run_server

  cfg = json.loads(get_config_path().read_text(encoding="utf-8"))
  host = cfg.get("host", "127.0.0.1")
  port = int(cfg.get("port", 9123))
  log(f"Starting HTTP server on {host}:{port}")

  thread = threading.Thread(target=run_server, args=(host, port), daemon=True, name="print-api")
  thread.start()
  return thread


def open_config_folder(_icon=None, _item=None) -> None:
  os.startfile(str(get_data_dir()))


def open_health(_icon=None, _item=None) -> None:
  webbrowser.open(health_url())


def open_log(_icon=None, _item=None) -> None:
  from logging_util import log_path

  path = log_path()
  if path.exists():
    os.startfile(str(path))


def current_printer_label() -> str:
  try:
    from server import resolve_printer

    return resolve_printer(None)
  except Exception:
    return "не найден"


def saved_printer_name() -> str:
  cfg = json.loads(get_config_path().read_text(encoding="utf-8"))
  return (cfg.get("default_printer") or "").strip()


def choose_printer(printer_name: str):
  def handler(_icon=None, _item=None) -> None:
    from server import set_default_printer

    set_default_printer(printer_name)
    log(f"Printer selected: {printer_name or '(Windows default)'}")

  return handler


def printer_is_checked(printer_name: str):
  def checked(_item) -> bool:
    return saved_printer_name() == printer_name

  return checked


def build_printer_menu():
  import pystray
  from server import list_printers

  items = [
    pystray.MenuItem(
      "Как в Windows (по умолчанию)",
      choose_printer(""),
      checked=printer_is_checked(""),
      radio=True,
    ),
  ]
  for name in list_printers():
    items.append(
      pystray.MenuItem(
        name,
        choose_printer(name),
        checked=printer_is_checked(name),
        radio=True,
      )
    )
  return pystray.Menu(*items)


def ensure_autostart_on_first_run() -> None:
  if not is_frozen() or not HAS_WIN32:
    return
  marker = get_data_dir() / ".autostart_done"
  if marker.exists():
    return
  if not autostart_enabled():
    set_autostart(True)
    log("Autostart enabled on first run")
  marker.write_text("1", encoding="utf-8")


def toggle_autostart(_icon=None, item=None) -> None:
  set_autostart(not item.checked)


def quit_agent(icon, _item=None) -> None:
  log("Agent exit requested")
  icon.visible = False
  icon.stop()
  os._exit(0)


def run_tray() -> None:
  import pystray._win32  # noqa: F401 — PyInstaller
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

  port = read_port()
  printer = current_printer_label()
  log(f"Tray icon starting on port {port}, printer={printer}")

  icon = pystray.Icon(
    "FulfillmentCRM PrintAgent",
    img,
    f"Fulfillment CRM — печать\n{printer}\n:{port}",
    menu=pystray.Menu(
      pystray.MenuItem("Проверка (health)", open_health, default=True),
      pystray.MenuItem("Принтер", build_printer_menu()),
      pystray.MenuItem("Папка настроек", open_config_folder),
      pystray.MenuItem("Журнал (agent.log)", open_log),
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


def run_headless_keepalive() -> None:
  """Если трей недоступен — агент всё равно слушает порт."""
  log("Headless mode (tray unavailable)")
  if HAS_WIN32:
    import ctypes

    ctypes.windll.user32.MessageBoxW(
      0,
      (
        "Агент печати запущен без иконки в трее.\n"
        f"Проверка: {health_url()}\n"
        f"Журнал: {get_data_dir() / 'agent.log'}"
      ),
      "Fulfillment CRM — Агент печати",
      0x40,
    )
  while True:
    time.sleep(3600)


def main() -> int:
  log("=== Agent start ===")
  if sys.platform != "win32":
    print("Агент печати поддерживается только на Windows.")
    return 1

  if not acquire_single_instance():
    log("Second instance blocked")
    if HAS_WIN32:
      import ctypes

      ctypes.windll.user32.MessageBoxW(
        0,
        "Агент печати Fulfillment CRM уже запущен.",
        "Fulfillment CRM",
        0x40,
      )
    return 0

  try:
    ensure_config()
    ensure_autostart_on_first_run()
    start_server_thread()
    if not wait_for_server():
      log("ERROR: HTTP server did not become ready")
      if HAS_WIN32:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
          0,
          (
            "Не удалось запустить сервер печати на порту "
            f"{read_port()}.\nПроверьте agent.log в папке настроек."
          ),
          "Fulfillment CRM — Ошибка агента",
          0x10,
        )
      return 1

    log("HTTP server ready")

    if is_frozen() or "--tray" in sys.argv:
      try:
        run_tray()
      except Exception:
        log_exception("run_tray")
        run_headless_keepalive()
      return 0

    from server import main as server_main

    server_main()
    return 0
  except Exception:
    log_exception("main")
    if HAS_WIN32:
      import ctypes

      ctypes.windll.user32.MessageBoxW(
        0,
        f"Агент печати завершился с ошибкой.\nСм. {get_data_dir() / 'agent.log'}",
        "Fulfillment CRM — Ошибка агента",
        0x10,
      )
    return 1


if __name__ == "__main__":
  raise SystemExit(main())
