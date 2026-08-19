"""Честный знак: валидация кодов и расшифровка ошибок WB."""
from __future__ import annotations

import re

from apps.integrations.wb_client import WBApiError

MARKING_MIN_LEN = 16
MARKING_MAX_LEN = 135

_GS = "\u001d"


def normalize_marking_code(raw: str) -> str:
  """Нормализация DataMatrix: GS-разделители, пробелы."""
  code = raw.strip()
  code = code.replace("\\u001D", _GS).replace("\\u001d", _GS)
  code = re.sub(r"\s+", "", code)
  return code


def validate_marking_code(raw: str) -> tuple[str, str | None]:
  """Вернуть (нормализованный код, текст ошибки или None)."""
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
