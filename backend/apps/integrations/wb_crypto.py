from cryptography.fernet import Fernet, InvalidToken

from django.conf import settings


class TokenCryptoError(Exception):
  pass


def _get_fernet() -> Fernet | None:
  key = settings.WB_TOKEN_ENCRYPTION_KEY
  if not key:
    return None
  return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(token: str) -> str:
  if not token:
    return ""
  fernet = _get_fernet()
  if not fernet:
    return token
  return fernet.encrypt(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
  if not encrypted:
    return ""
  fernet = _get_fernet()
  if not fernet:
    return encrypted
  try:
    return fernet.decrypt(encrypted.encode()).decode()
  except InvalidToken as exc:
    raise TokenCryptoError("Не удалось расшифровать токен WB") from exc
