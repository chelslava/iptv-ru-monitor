"""Discovery: сбор записей каналов и потоков из подключённых источников."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx

from ..domain.source import SourceConfig
from ..settings import load_sources
from .base import DiscoveredStream, SourceAdapter, parse_m3u
from .custom_m3u import CustomM3uAdapter
from .free_tv import FreeTvAdapter
from .iptv_org import IptvOrgAdapter
from .remote_m3u import RemoteM3uAdapter

logger = logging.getLogger(__name__)

_ADAPTERS: dict[str, type[SourceAdapter]] = {
    "iptv_org": IptvOrgAdapter,
    "free_tv": FreeTvAdapter,
    "custom_m3u": CustomM3uAdapter,
    "remote_m3u": RemoteM3uAdapter,
}


def register_adapter(name: str, adapter_cls: type[SourceAdapter]) -> None:
    """Зарегистрировать пользовательский адаптер (расширяемость источников)."""
    _ADAPTERS[name] = adapter_cls


def create_adapter(config: SourceConfig) -> SourceAdapter:
    try:
        adapter_cls = _ADAPTERS[config.adapter]
    except KeyError as exc:
        raise ValueError(
            f"unknown adapter {config.adapter!r} for source {config.id!r}; "
            f"available: {sorted(_ADAPTERS)}"
        ) from exc
    return adapter_cls(config)


def load_adapters(config_dir: Path) -> list[SourceAdapter]:
    """Создать адаптеры для всех включённых источников."""
    sources = [s for s in load_sources(config_dir) if s.enabled]
    return [create_adapter(source) for source in sources]


async def fetch_all(
    adapters: list[SourceAdapter], client: httpx.AsyncClient
) -> list[DiscoveredStream]:
    """Собрать записи из всех источников; ошибка одного не валит остальные."""

    async def _fetch_one(adapter: SourceAdapter) -> list[DiscoveredStream]:
        try:
            entries = await adapter.fetch(client)
        except Exception as exc:
            # Ошибка одного источника не должна валить сбор целиком;
            # полный traceback — только на уровне DEBUG.
            logger.error("source %s failed: %s", adapter.source_id, exc)
            logger.debug("source %s traceback", adapter.source_id, exc_info=True)
            return []
        logger.info("source %s: %d entries", adapter.source_id, len(entries))
        return entries

    results = await asyncio.gather(*(_fetch_one(a) for a in adapters))
    return [entry for chunk in results for entry in chunk]


__all__ = [
    "DiscoveredStream",
    "SourceAdapter",
    "create_adapter",
    "fetch_all",
    "load_adapters",
    "parse_m3u",
]
