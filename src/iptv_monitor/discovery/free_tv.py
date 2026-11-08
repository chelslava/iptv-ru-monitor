"""Адаптер Free-TV/IPTV: общий плейлист с фильтром по стране."""

from __future__ import annotations

import httpx

from ..domain.source import SourceConfig
from .base import DiscoveredStream, SourceAdapter, parse_m3u


def _matches_country(entry: DiscoveredStream, country: str) -> bool:
    """Грубый фильтр по стране: group-title или суффикс tvg-id.

    Структура плейлиста Free-TV меняется — при реализации проверить фактическую
    разметку групп и при необходимости уточнить (см. docs/SOURCE_POLICY.md).
    """
    cc = country.lower()
    if entry.tvg_id and entry.tvg_id.lower().endswith(f".{cc}"):
        return True
    if entry.group_title and cc in entry.group_title.lower():
        return True
    return False


class FreeTvAdapter(SourceAdapter):
    """Загрузка плейлиста Free-TV и фильтрация записей по стране."""

    def __init__(self, config: SourceConfig) -> None:
        super().__init__(config)
        if not config.url:
            raise ValueError(f"free_tv adapter requires url (source {config.id})")
        self._url = config.url

    async def fetch(self, client: httpx.AsyncClient) -> list[DiscoveredStream]:
        response = await client.get(self._url, follow_redirects=True)
        response.raise_for_status()
        entries = parse_m3u(response.text, self.source_id)
        if self.config.country:
            entries = [e for e in entries if _matches_country(e, self.config.country)]
        return entries
