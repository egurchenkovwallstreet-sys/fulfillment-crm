"""Локальный мост печати для Xprinter 365/370 (Windows).

Запускается на ПК склада, куда подключён USB-принтер.
CRM в браузере шлёт PNG base64 → печать без диалога Chrome.
"""
from __future__ import annotations

import base64
import io
import json
import sys

from flask import Flask, jsonify, request
from flask_cors import CORS
from PIL import Image

try:
  import win32con
  import win32print
  import win32ui
  from PIL import ImageWin

  HAS_WIN32 = True
except ImportError:
  HAS_WIN32 = False

from paths import get_config_path, get_example_config_path

CONFIG_PATH = get_config_path()
EXAMPLE_CONFIG = get_example_config_path()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})


def load_config() -> dict:
  if CONFIG_PATH.exists():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
  if EXAMPLE_CONFIG.exists():
    return json.loads(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
  return {
    "host": "127.0.0.1",
    "port": 9123,
    "default_printer": "",
    "print_mode": "full_page",
    "jobs": {
      "fbs_sticker": {"width_mm": 58, "height_mm": 40},
      "supply_sticker": {"width_mm": 58, "height_mm": 40},
      "cell_label": {"width_mm": 75, "height_mm": 120},
    },
  }


def save_config(cfg: dict) -> None:
  CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def list_printers() -> list[str]:
  if not HAS_WIN32:
    return []
  flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
  printers = win32print.EnumPrinters(flags)
  return [item[2] for item in printers]


def resolve_printer(name: str | None) -> str:
  if not HAS_WIN32:
    raise RuntimeError("Печать доступна только на Windows с pywin32")
  if name:
    return name
  cfg = load_config()
  configured = (cfg.get("default_printer") or "").strip()
  if configured:
    return configured
  return win32print.GetDefaultPrinter()


def job_size(job_type: str) -> tuple[float, float]:
  cfg = load_config()
  jobs = cfg.get("jobs") or {}
  spec = jobs.get(job_type) or jobs.get("fbs_sticker") or {"width_mm": 58, "height_mm": 40}
  return float(spec.get("width_mm", 58)), float(spec.get("height_mm", 40))


def print_mode() -> str:
  return str(load_config().get("print_mode") or "full_page").strip().lower()


def _fit_image_to_box(img: Image.Image, width_px: int, height_px: int) -> Image.Image:
  if width_px < 1 or height_px < 1:
    return img
  src_w, src_h = img.size
  scale = min(width_px / src_w, height_px / src_h)
  target_w = max(1, int(src_w * scale))
  target_h = max(1, int(src_h * scale))
  return img.resize((target_w, target_h), Image.LANCZOS)


def print_png(
  image_b64: str,
  *,
  job_type: str,
  printer_name: str | None = None,
) -> dict:
  if not HAS_WIN32:
    raise RuntimeError("Установите pywin32: pip install pywin32")

  raw = base64.b64decode(image_b64, validate=True)
  img = Image.open(io.BytesIO(raw))
  if img.mode != "RGB":
    img = img.convert("RGB")

  width_mm, height_mm = job_size(job_type)
  printer = resolve_printer(printer_name)
  mode = print_mode()

  hdc = win32ui.CreateDC()
  hdc.CreatePrinterDC(printer)

  if mode == "full_page":
    width_px = hdc.GetDeviceCaps(win32con.HORZRES)
    height_px = hdc.GetDeviceCaps(win32con.VERTRES)
    width_mm = round(width_px / hdc.GetDeviceCaps(win32con.LOGPIXELSX) * 25.4, 1)
    height_mm = round(height_px / hdc.GetDeviceCaps(win32con.LOGPIXELSY) * 25.4, 1)
    img = _fit_image_to_box(img, width_px, height_px)
  else:
    logpixelsx = hdc.GetDeviceCaps(win32con.LOGPIXELSX)
    logpixelsy = hdc.GetDeviceCaps(win32con.LOGPIXELSY)
    width_px = max(1, int(width_mm / 25.4 * logpixelsx))
    height_px = max(1, int(height_mm / 25.4 * logpixelsy))
    img = img.resize((width_px, height_px), Image.LANCZOS)

  hdc.StartDoc(f"CRM {job_type}")
  hdc.StartPage()
  dib = ImageWin.Dib(img)
  dib.draw(hdc.GetHandleOutput(), (0, 0, img.size[0], img.size[1]))
  hdc.EndPage()
  hdc.EndDoc()
  hdc.DeleteDC()

  return {
    "printer": printer,
    "print_mode": mode,
    "width_mm": width_mm,
    "height_mm": height_mm,
    "width_px": img.size[0],
    "height_px": img.size[1],
  }


@app.get("/health")
def health():
  cfg = load_config()
  printer = ""
  try:
    printer = resolve_printer(None) if HAS_WIN32 else ""
  except Exception:
    printer = ""
  return jsonify({
    "ok": True,
    "platform": sys.platform,
    "win32": HAS_WIN32,
    "printer": printer,
    "print_mode": print_mode(),
    "port": cfg.get("port", 9123),
  })


@app.get("/printers")
def printers():
  return jsonify({"printers": list_printers()})


@app.get("/config")
def get_config():
  return jsonify(load_config())


@app.post("/config")
def set_config():
  data = request.get_json(silent=True) or {}
  cfg = load_config()
  if "default_printer" in data:
    cfg["default_printer"] = str(data["default_printer"] or "")
  if "print_mode" in data:
    mode = str(data["print_mode"] or "").strip().lower()
    if mode in ("full_page", "label"):
      cfg["print_mode"] = mode
  save_config(cfg)
  return jsonify({"ok": True, "config": cfg})


@app.post("/print")
def print_job():
  data = request.get_json(silent=True) or {}
  image_b64 = (data.get("image_base64") or data.get("image") or "").strip()
  if not image_b64:
    return jsonify({"detail": "Укажите image_base64"}), 400

  job_type = (data.get("job_type") or "fbs_sticker").strip()
  printer_name = (data.get("printer") or "").strip() or None

  try:
    meta = print_png(image_b64, job_type=job_type, printer_name=printer_name)
  except Exception as exc:
    return jsonify({"detail": str(exc)}), 500

  return jsonify({"ok": True, **meta})


def run_server(host: str, port: int) -> None:
  app.run(host=host, port=port, threaded=True, use_reloader=False)


def main():
  cfg = load_config()
  host = cfg.get("host", "127.0.0.1")
  port = int(cfg.get("port", 9123))
  print(f"Print bridge: http://{host}:{port}  win32={HAS_WIN32}")
  if HAS_WIN32:
    try:
      print(f"Printer: {resolve_printer(None)}")
    except Exception as exc:
      print(f"Printer: not set ({exc})")
  run_server(host, port)


if __name__ == "__main__":
  main()
