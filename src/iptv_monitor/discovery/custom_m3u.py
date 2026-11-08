"""Адаптер собственных M3U-списков проекта (локальные файлы)."""

from __future__ import annotations

import httpx

from ..domain.source import SourceConfig
from .base import DiscoveredStream, SourceAdapter, parse_m3u


class CustomM3uAdapter(SourceAdapter):
    """Чтение локального M3U-файла, указанного в config/sources.yaml (path)."""

    def __init__(self, config: SourceConfig) -> None:
        super().__init__(config)
        if not config.path:
            raise ValueError(f"custom_m3u adapter requires path (source {config.id})")
        self._path = config.path

    async def fetch(self, client: httpx.AsyncClient) -> list[DiscoveredStream]:
        text = self._path.read_text(encoding="utf-8", errors="replace")
        return parse_m3u(text, self.source_id)
