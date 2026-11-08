"""Логирование с редакцией секретов.

Токены, ключи и приватные параметры URL не должны попадать в логи и отчёты.
Фильтр применяется ко всем записям корневого логгера.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import parse_qsl, urlsplit, urlunsplit

_TOKEN_KEYS = {
    "token",
    "key",
    "auth",
    "signature",
    "password",
    "pwd",
    "secret",
    "expires",
    "expire",
    "jwt",
    "access_token",
    "api_key",
    "hash",
}

_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_LONG_VALUE_RE = re.compile(r"^[A-Za-z0-9_\-\.]{24,}$")  # похоже на токен/base64

_MASK = "***"


def redact_query_value(key: str, value: str) -> str:
    """Маскировать значение параметра, если ключ подозрителен или значение похоже на токен."""
    if key.lower() in _TOKEN_KEYS or _LONG_VALUE_RE.match(value):
        return _MASK
    return value


def redact_url(url: str) -> str:
    """Убрать секретные значения из query string URL."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    kept: list[str] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        kept.append(f"{key}={redact_query_value(key, value)}")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(kept), parts.fragment))


def redact_text(text: str) -> str:
    """Применить редакцию ко всем URL внутри произвольного текста."""
    return _URL_RE.sub(lambda m: redact_url(m.group(0)), text)


class RedactingFilter(logging.Filter):
    """Фильтр логов: маскирует секреты в сообщении и строковых аргументах."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(str(record.msg))
        if record.args:
            record.args = (
                tuple(redact_text(arg) if isinstance(arg, str) else arg for arg in record.args)
                if isinstance(record.args, tuple)
                else record.args
            )
        return True


def setup_logging(level: str = "INFO") -> None:
    """Настроить корневой логгер с редактирующим фильтром."""
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    )
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
