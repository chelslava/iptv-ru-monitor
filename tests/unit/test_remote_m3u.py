"""Тесты адаптера remote_m3u (внешние M3U-плейлисты)."""

from __future__ import annotations

import httpx
import pytest

from iptv_monitor.discovery import create_adapter
from iptv_monitor.discovery.remote_m3u import RemoteM3uAdapter
from iptv_monitor.domain.source import SourceConfig

PLAYLIST = """#EXTM3U
#EXTINF:-1 tvg-id="1tv.ru" group-title="Общие",Первый канал
https://stream.example.org/1tv/index.m3u8
#EXTINF:-1 group-title="Спорт",Матч ТВ
https://stream.example.org/match/index.m3u8
"""


def _config(url: str | None = "https://lists.example.org/ru.m3u") -> SourceConfig:
    return SourceConfig(
        id="remote-list", adapter="remote_m3u", url=url, country="RU", public_policy="review"
    )


async def test_fetch_parses_entries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://lists.example.org/ru.m3u"
        return httpx.Response(200, text=PLAYLIST)

    adapter = create_adapter(_config())
    assert isinstance(adapter, RemoteM3uAdapter)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        entries = await adapter.fetch(client)
    assert len(entries) == 2
    assert entries[0].source_id == "remote-list"
    assert entries[0].tvg_id == "1tv.ru"
    assert entries[0].url.endswith("1tv/index.m3u8")


async def test_http_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    adapter = create_adapter(_config())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.fetch(client)


def test_missing_url_rejected() -> None:
    with pytest.raises(ValueError, match="requires url"):
        create_adapter(_config(url=None))
