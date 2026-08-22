"""Честный знак: валидация кодов и расшифровка ошибок WB."""
from __future__ import annotations

import re

from apps.integrations.wb_client import WBApiError

MARKING_MIN_LEN = 16
MARKING_MAX_LEN = 135

_GS = "\u001d"

_GS_ALIASES = (
  "\\u001D",
  "\\u001d",
  "\\x1D",
  "\\x1d",
  "{GS}",
  "{gs}",
  "[GS]",
  "[gs]",
  "<GS>",
  "<gs>",
)

# AIM-префикс сканера: ]d2 (DataMatrix), ]C1 (GS1-128) и т.п.
_AIM_PREFIX = re.compile(r"^\][A-Za-z][0-9]")
_CYRILLIC = re.compile(r"[А-Яа-яЁё]")
# Криптохвост ЧЗ: 91 + 4 символа ключа + 92 + подпись
_CRYPTO_TAIL = re.compile(r"(91[A-Za-z0-9]{4})(92)")


def _restore_group_separators(code: str) -> str:
  """Вернуть GS перед AI 91 и 92, если сканер их выкинул."""
  if _GS in code:
    return code
  if "|" in code and code.count("|") <= 2:
    return code.replace("|", _GS)
  restored, n = _CRYPTO_TAIL.subn(_GS + r"\1" + _GS + r"\2", code, count=1)
  return restored if n else code


def normalize_marking_code(raw: str) -> str:
  """Нормализация DataMatrix: GS-разделители, AIM-префикс, пробелы."""
  code = raw.strip()
  for alias in _GS_ALIASES:
    code = code.replace(alias, _GS)
  code = _AIM_PREFIX.sub("", code)
  code = code.lstrip(_GS)
  code = re.sub(r"\s+", "", code)
  return _restore_group_separators(code)


def validate_marking_code(raw: str) -> tuple[str, str | None]:
  """Вернуть (нормализованный код, текст ошибки или None)."""
  if _CYRILLIC.search(raw):
    return raw.strip(), (
      "Сканер печатает русскими буквами. "
      "Переключите раскладку Windows на ENG и отсканируйте код заново."
    )

  code = normalize_marking_code(raw)
  if not code:
    return "", "Код Честного знака пустой — отсканируйте DataMatrix с упаковки"
  if len(code) < MARKING_MIN_LEN:
    return code, (
      f"Код слишком короткий ({len(code)} симв.). "
      f"Минимум {MARKING_MIN_LEN}. Проверьте, что сканер считал DataMatrix полностью."
    )
  if len(code) > MARKING_MAX_LEN:
    return code, (
      f"Код слишком длинный ({len(code)} симв.). "
      f"Максимум {MARKING_MAX_LEN}. Возможно, сканер добавил лишние символы."
    )
  if not re.match(r"^[\x20-\x7E\u001d]+$", code):
    return code, "Код содержит недопустимые символы. Отсканируйте DataMatrix заново."
  return code, None


def parse_wb_marking_error(exc: WBApiError) -> str:
  """Понятное сообщение об ошибке привязки ЧЗ к заказу WB."""
  text = str(exc).lower()
  body = text

  if exc.status_code == 401:
    return "Токен WB недействителен — обновите токен селлера в админке."
  if exc.status_code == 429:
    return "Превышен лимит запросов WB. Подождите минуту и повторите привязку ЧЗ."

  patterns: list[tuple[str, str]] = [
    ("sgtinnotfound", "Код ЧЗ не найден в системе «Честный знак». Проверьте код или замените товар."),
    ("sgtinalready", "Этот код ЧЗ уже привязан к другому заказу. Используйте другой экземпляр товара."),
    ("sgtinalreadyinuse", "Этот код ЧЗ уже привязан к другому заказу. Используйте другой экземпляр товара."),
    ("sgtinhasinvalidsymbols", "Код ЧЗ содержит недопустимые символы. Отсканируйте DataMatrix заново."),
    ("sgtinhasnonlatinsymbols", "Код ЧЗ содержит недопустимые символы. Отсканируйте DataMatrix заново."),
    ("sgtininvalidpattern", "Неверный формат кода ЧЗ. Отсканируйте DataMatrix с упаковки."),
    ("not in confirm", "Заказ не в статусе «На сборке» в WB — обновите заказы из WB."),
    ("status", "Заказ в неподходящем статусе WB для привязки ЧЗ. Обновите заказы из WB."),
    ("requiredmeta", "WB не требует маркировку для этого заказа — обратитесь к администратору."),
    ("409", "WB отклонил привязку ЧЗ: проверьте код и статус заказа в личном кабинете."),
  ]

  for needle, message in patterns:
    if needle in body:
      return message

  if exc.status_code == 404:
    return "Заказ не найден в WB. Обновите заказы из WB и повторите."
  if exc.status_code == 400:
    return f"WB отклонил код ЧЗ: {exc}. Проверьте код или замените товар."
  if exc.status_code and exc.status_code >= 500:
    return "Сервер WB временно недоступен. Повторите через минуту."

  return f"Ошибка привязки ЧЗ в WB: {exc}"
