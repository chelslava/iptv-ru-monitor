"""Сопоставление каналов с категориями (config/categories.yaml)."""

from __future__ import annotations

from ..domain.enums import Category
from ..settings import CategoryRule


def classify_channel(
    *,
    name: str,
    group_title: str | None,
    rules: list[CategoryRule],
    default: Category = Category.GENERAL,
) -> Category:
    """Определить категорию по названию и группе плейлиста.

    Паттерны — регистронезависимые подстроки; первый подходящий выигрывает.
    """
    haystack = " ".join(part for part in (name, group_title) if part).lower()
    for rule in rules:
        if any(pattern.lower() in haystack for pattern in rule.patterns):
            return rule.category
    return default
