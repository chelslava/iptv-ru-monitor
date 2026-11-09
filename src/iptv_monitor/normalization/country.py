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
    UK GB
    """.split()
)

# Автономный двухбуквенный токен в названии/группе («UZ», «(KZ)»).
_CC_TOKEN_RE = re.compile(r"\b([A-Z]{2})\b")

# Слово ПОСЛЕ кода маркирует событие, а не страну: «US Open» — турнир,
# «EU Cup» — соревнование (issue #15). Такие совпадения отбрасываются.
_EVENT_WORDS = frozenset(
    {"open", "cup", "tour", "series", "championship", "league", "masters", "games", "classic"}
)

# Явные бренды-исключения (два слова вокруг кода), добавляются по мере
# обнаружения ложных срабатываний в отчёте discover.
_BRAND_NAMES = frozenset({"us open", "uk open", "us weekly", "uk top"})

# Не-ISO синонимы, встречающиеся в источниках, -> ISO 3166-1 alpha-2
# (issue #26): «UK» из tvg-id/названий даёт нестандартный код страны
# и channel_id «uk-...»; канон — GB.
_CC_ALIASES = {"UK": "GB"}


def _canonical_cc(code: str) -> str:
    """Канонический ISO-код: синонимы источников приводятся к ISO."""
    return _CC_ALIASES.get(code, code)


def normalize_country(code: str | None) -> str | None:
    """Вернуть код страны в верхнем регистре либо None, если код невалиден."""
    if not code:
        return None
    code = code.strip().upper()
    return _canonical_cc(code) if _COUNTRY_RE.match(code) else None


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
        return _canonical_cc(cc) if cc in _KNOWN_CC else None
    return None


def _clean_name_hits(text: str) -> str | None:
    """Первый код страны в тексте без событийных/брендовых ложных срабатываний."""
    words = text.split()
    for match in _CC_TOKEN_RE.finditer(text):
        cc = match.group(1)
        if cc not in _KNOWN_CC:
            continue
        # Слово после кода: «US Open» -> событие, пропускаем.
        end_words = text[match.end() :].lstrip().lower().split(maxsplit=1)
        if end_words and end_words[0].strip(".,()[]") in _EVENT_WORDS:
            continue
        # Два слова вокруг кода как бренд-фраза.
        word_index = len(text[: match.start()].split())
        phrase = " ".join(words[max(0, word_index - 1) : word_index + 2]).lower()
        if phrase in _BRAND_NAMES:
            continue
        return _canonical_cc(cc)
    return None


def country_from_name(name: str | None, group_title: str | None = None) -> str | None:
    """Код страны по автономному токену в названии/группе.

    «Milliy TV UZ» -> UZ; «Первый канал» -> None (обычные слова не совпадают
    с известными кодами). Совпадение только в верхнем регистре. Группа
    надёжнее имени (категорийные метаданные) — при конфликте побеждает
    группа; событийные фразы («US Open») и явные бренды не матчатся (issue #15).
    """
    if group_title:
        group_code = _clean_name_hits(group_title)
        if group_code:
            return group_code
    if name:
        return _clean_name_hits(name)
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
