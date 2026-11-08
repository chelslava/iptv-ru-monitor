"""Нормализация названий каналов."""

from __future__ import annotations

import re
import unicodedata

# Токены качества, отбрасываемые при сравнении названий.
_QUALITY_TOKENS = {
    "hd",
    "fhd",
    "sd",
    "uhd",
    "4k",
    "8k",
    "4к",
    "8к",
    "1080p",
    "1080i",
    "720p",
    "576i",
    "480p",
    "h264",
    "h265",
    "hevc",
}

_BRACKETS_RE = re.compile(r"[\(\[<][^\)\]>]*[\)\]>]")
_NON_WORD_RE = re.compile(r"[^\w\s]+", re.UNICODE)


def normalize_name(name: str) -> str:
    """Каноническая форма названия для сравнения и дедупликации.

    Приведение юникода, снятие скобочных уточнений, отбрасывание пунктуации,
    нижний регистр, удаление суффиксов качества (HD/FHD/4K/...).
    """
    text = unicodedata.normalize("NFKC", name)
    text = _BRACKETS_RE.sub(" ", text)
    text = text.replace("&", " и ")
    text = _NON_WORD_RE.sub(" ", text)
    tokens = [token for token in text.lower().split() if token]
    while tokens and tokens[-1] in _QUALITY_TOKENS:
        tokens.pop()
    return " ".join(tokens)


def build_channel_id(name: str, country: str) -> str:
    """Стабильный внутренний ID канала: <страна>-<слаг названия>.

    Детерминирован: одинаковые входные данные дают одинаковый ID
    (принцип воспроизводимых сборок).
    """
    slug = re.sub(r"[^a-z0-9а-яё]+", "-", normalize_name(name).replace("ё", "е"))
    slug = slug.strip("-") or "channel"
    return f"{country.lower()}-{slug[:60]}"
