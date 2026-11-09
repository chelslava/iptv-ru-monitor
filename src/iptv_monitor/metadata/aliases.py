"""Таблица алиасов для сопоставления каналов с EPG."""

from __future__ import annotations

from ..normalization.channel_names import normalize_name
from ..settings import AliasRule


class AliasIndex:
    """Индекс ручных алиасов по нормализованному названию канала.

    Алиасы скоупятся страной (issue #22): правило с country="RU" срабатывает
    только для канала страны RU; правило без страны — глобальное.
    """

    def __init__(self, rules: list[AliasRule]) -> None:
        self._by_name: dict[str, list[AliasRule]] = {}
        for rule in rules:
            self._by_name.setdefault(normalize_name(rule.name), []).append(rule)

    def lookup(self, *names: str | None, country: str | None = None) -> AliasRule | None:
        """Найти алиас по названию или альтернативным названиям.

        ``country`` — страна канала: правило должно быть глобальным или
        относиться к этой стране (RU-алиас не срабатывает для UA-канала).
        """
        for name in names:
            if not name:
                continue
            for rule in self._by_name.get(normalize_name(name), []):
                if rule.country is None or rule.country == country:
                    return rule
        return None

    def __len__(self) -> int:
        return sum(len(rules) for rules in self._by_name.values())
