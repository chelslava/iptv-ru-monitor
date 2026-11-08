"""Таблица алиасов для сопоставления каналов с EPG."""

from __future__ import annotations

from ..normalization.channel_names import normalize_name
from ..settings import AliasRule


class AliasIndex:
    """Индекс ручных алиасов по нормализованному названию канала."""

    def __init__(self, rules: list[AliasRule]) -> None:
        self._by_name: dict[str, AliasRule] = {}
        for rule in rules:
            self._by_name.setdefault(normalize_name(rule.name), rule)

    def lookup(self, *names: str | None) -> AliasRule | None:
        """Найти алиас по названию или альтернативным названиям."""
        for name in names:
            if not name:
                continue
            rule = self._by_name.get(normalize_name(name))
            if rule:
                return rule
        return None

    def __len__(self) -> int:
        return len(self._by_name)
