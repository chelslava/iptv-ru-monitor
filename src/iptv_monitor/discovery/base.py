"""Базовый интерфейс адаптера источника и разбор M3U."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

import httpx
from pydantic import BaseModel

from ..domain.source import SourceConfig

_ATTR_RE = re.compile(r'([A-Za-z0-9_-]+)="([^"]*)"')


class DiscoveredStream(BaseModel):
    """Сырая запись канала/потока из источника, до нормализации."""

    source_id: str
    name: str
    url: str
    country: str | None = None
    language: str | None = None
    tvg_id: str | None = None
    tvg_name: str | None = None
    tvg_logo: str | None = None
    group_title: str | None = None


class SourceAdapter(ABC):
    """Общий интерфейс источника данных (см. архитектуру, раздел 6)."""

    def __init__(self, config: SourceConfig) -> None:
        self.config = config

    @property
    def source_id(self) -> str:
        return self.config.id

    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient) -> list[DiscoveredStream]:
        """Получить записи каналов и потоков из источника."""


def parse_m3u(text: str, source_id: str) -> list[DiscoveredStream]:
    """Разобрать M3U-плейлист в записи DiscoveredStream.

    Поддерживаются атрибуты #EXTINF (tvg-id, tvg-name, tvg-logo, group-title);
    остальные директивы (#EXTVLCOPT, #KODIPROP и т. п.) пропускаются.
    """
    entries: list[DiscoveredStream] = []
    pending: DiscoveredStream | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            attrs = dict(_ATTR_RE.findall(line))
            comma_idx = line.rfind(",")
            name = line[comma_idx + 1 :].strip() if comma_idx != -1 else ""
            pending = DiscoveredStream(
                source_id=source_id,
                url="pending",  # будет заменён ниже
                name=name or attrs.get("tvg-name") or attrs.get("tvg-id") or "Unknown",
                tvg_id=attrs.get("tvg-id") or None,
                tvg_name=attrs.get("tvg-name") or None,
                tvg_logo=attrs.get("tvg-logo") or None,
                group_title=attrs.get("group-title") or None,
            )
        elif line.startswith("#"):
            continue
        elif pending is not None:
            if line.startswith(("http://", "https://")):
                pending.url = line
                entries.append(pending)
            pending = None

    return entries
