"""Нормализация и определение кода страны (ISO 3166-1 alpha-2).

Страна записи определяется в порядке приоритета:
1. суффикс tvg-id (формат iptv-org: `1tv.ru`, `2x2.ru@SD`);
2. явное поле записи из источника;
3. автономный код страны в названии/группе (`Milliy TV UZ` -> UZ);
4. страна источника из config/sources.yaml (текущее поведение MVP).
"""

from __future__ import annotations

import re

_COUNTRY_RE = re.compile(r"^[A-Za-z]{2}$")

# Известные коды стран (регион + частые мировые), чтобы отсекать ложные
# совпадения вида «TV», «HD», «FM» при детекции по названию.
_KNOWN_CC = frozenset(
    """
    RU UA BY KZ UZ AZ GE AM KG TJ TM MD
    LT LV EE FI SE NO DK PL DE FR IT ES NL BE AT CH CZ SK HU RO BG GR
    TR IL AE SA IR IQ IN CN JP KR
    US CA MX BR AR CL CO AU NZ ZA EG
    UK
    """.split()
)

# Автономный двухбуквенный токен в названии/группе («UZ», «(KZ)»).
_CC_TOKEN_RE = re.compile(r"\b([A-Z]{2})\b")


def normalize_country(code: str | None) -> str | None:
    """Вернуть код страны в верхнем регистре либо None, если код невалиден."""
    if not code:
        return None
    code = code.strip().upper()
    return code if _COUNTRY_RE.match(code) else None


def country_from_tvg_id(tvg_id: str | None) -> str | None:
    """Код страны из суффикса tvg-id: `1tv.ru` -> RU, `2x2.ru@SD` -> RU."""
    if not tvg_id:
        return None
    base = tvg_id.split("@", 1)[0].lower()
    parts = base.split(".")
    if len(parts) < 2:
        return None
    suffix = parts[-1]
    if len(suffix) == 2 and suffix.isalpha():
        cc = suffix.upper()
        return cc if cc in _KNOWN_CC else None
    return None


def country_from_name(name: str | None, group_title: str | None = None) -> str | None:
    """Код страны по автономному токену в названии/группе.

    «Milliy TV UZ» -> UZ; «Первый канал» -> None (обычные слова не совпадают
    с известными кодами). Совпадение только в верхнем регистре.
    """
    for text in filter(None, (name, group_title)):
        for match in _CC_TOKEN_RE.finditer(text):
            cc = match.group(1)
            if cc in _KNOWN_CC:
                return cc
    return None


def detect_country(
    *,
    tvg_id: str | None,
    entry_country: str | None,
    name: str | None,
    group_title: str | None,
    source_country: str | None,
) -> str | None:
    """Определить страну записи по убыванию надёжности признаков."""
    return (
        country_from_tvg_id(tvg_id)
        or normalize_country(entry_country)
        or country_from_name(name, group_title)
        or normalize_country(source_country)
    )
