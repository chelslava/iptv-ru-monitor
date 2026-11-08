"""Адаптер произвольного удалённого M3U-плейлиста.

Источник описывается в config/sources.yaml адаптером remote_m3u:
URL считается доверенной конфигурацией репозитория, поэтому запрос
выполняется напрямую с автоследованием редиректов. Страна записей
наследуется от источника (поле country).
"""

from __future__ import annotations

import httpx

from ..domain.source import SourceConfig
from .base import DiscoveredStream, SourceAdapter, parse_m3u


class RemoteM3uAdapter(SourceAdapter):
    """Загрузка внешнего M3U-плейлиста по URL (см. docs/SOURCE_POLICY.md)."""

    def __init__(self, config: SourceConfig) -> None:
        super().__init__(config)
        if not config.url:
            raise ValueError(f"remote_m3u adapter requires url (source {config.id})")
        self._url = config.url

    async def fetch(self, client: httpx.AsyncClient) -> list[DiscoveredStream]:
        response = await client.get(self._url, follow_redirects=True)
        response.raise_for_status()
        return parse_m3u(response.text, self.source_id)
