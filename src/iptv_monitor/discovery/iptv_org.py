"""Адаптер каталога iptv-org (https://iptv-org.github.io)."""

from __future__ import annotations

import httpx

from ..domain.source import SourceConfig
from .base import DiscoveredStream, SourceAdapter, parse_m3u


class IptvOrgAdapter(SourceAdapter):
    """Загрузка странового M3U-каталога iptv-org.

    URL считается доверенной конфигурацией репозитория (config/sources.yaml),
    поэтому запрос выполняется напрямую с автоследованием редиректов.
    """

    def __init__(self, config: SourceConfig) -> None:
        super().__init__(config)
        if not config.url:
            raise ValueError(f"iptv_org adapter requires url (source {config.id})")
        self._url = config.url

    async def fetch(self, client: httpx.AsyncClient) -> list[DiscoveredStream]:
        response = await client.get(self._url, follow_redirects=True)
        response.raise_for_status()
        return parse_m3u(response.text, self.source_id)
