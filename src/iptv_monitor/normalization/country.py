"""Нормализация кода страны (ISO 3166-1 alpha-2)."""

from __future__ import annotations

import re

_COUNTRY_RE = re.compile(r"^[A-Za-z]{2}$")


def normalize_country(code: str | None) -> str | None:
    """Вернуть код страны в верхнем регистре либо None, если код невалиден."""
    if not code:
        return None
    code = code.strip().upper()
    return code if _COUNTRY_RE.match(code) else None
