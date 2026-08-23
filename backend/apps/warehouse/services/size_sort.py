"""Сортировка размеров одежды (RU/EU) по возрастанию."""
from __future__ import annotations

import re

_LETTER_ORDER = {
  "xxxs": 0,
  "xxs": 1,
  "xs": 2,
  "s": 3,
  "m": 4,
  "l": 5,
  "xl": 6,
  "xxl": 7,
  "xxxl": 8,
  "xxxxl": 9,
}


def _parse_numeric_size(value: str) -> int | None:
  text = value.strip().replace(",", ".")
  match = re.search(r"\d+(?:\.\d+)?", text)
  if not match:
    return None
  try:
    return int(float(match.group()))
  except ValueError:
    return None


def size_sort_key(wb_size: str, tech_size: str) -> tuple:
  """Ключ сортировки: сначала RU (wbSize), затем EU (techSize)."""
  primary = (wb_size or "").strip()
  secondary = (tech_size or "").strip()
  label = primary or secondary
  lower = label.lower()

  if lower in ("one size", "onesize", "универсальный", "0"):
    return (2, 0, lower)

  num = _parse_numeric_size(primary) if primary else None
  if num is None and secondary:
    num = _parse_numeric_size(secondary)
  if num is not None:
    return (0, num, lower)

  letter = re.sub(r"[^a-z]", "", lower)
  if letter in _LETTER_ORDER:
    return (1, _LETTER_ORDER[letter], lower)

  return (3, 0, lower)
