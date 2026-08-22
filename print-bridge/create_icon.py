"""Создаёт assets/icon.ico для сборки агента."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)


def make_icon(size: int) -> Image.Image:
  img = Image.new("RGBA", (size, size), (37, 99, 235, 255))
  draw = ImageDraw.Draw(img)
  font_size = max(12, size // 3)
  try:
    font = ImageFont.truetype("arial.ttf", font_size)
  except OSError:
    font = ImageFont.load_default()
  text = "FF"
  bbox = draw.textbbox((0, 0), text, font=font)
  tw = bbox[2] - bbox[0]
  th = bbox[3] - bbox[1]
  draw.text(((size - tw) / 2, (size - th) / 2 - 1), text, fill="white", font=font)
  return img


def main() -> None:
  sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
  images = [make_icon(s) for s, _ in sizes]
  out = ASSETS / "icon.ico"
  images[0].save(out, format="ICO", sizes=sizes, append_images=images[1:])
  print(f"Saved {out}")


if __name__ == "__main__":
  main()
