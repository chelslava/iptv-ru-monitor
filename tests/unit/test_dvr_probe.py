"""Тесты DVR-пробы Flussonic и catchup-атрибутов плейлиста (issue #10)."""

from __future__ import annotations

import httpx
import pytest

from iptv_monitor.checking import (
    flussonic_catchup_source,
    flussonic_timeshift_url,
    probe_dvr,
)
from iptv_monitor.generators import M3UEntry, render_m3u

# Валидный media playlist с сегментами (ответ DVR-пробы).
MEDIA = "#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\n1699-06000.ts\n"


def test_flussonic_timeshift_url() -> None:
    assert (
        flussonic_timeshift_url("http://h.tv/stream/playlist.m3u8", 1700000000)
        == "http://h.tv/stream/timeshift_abs-1700000000.m3u8"
    )
    # вложенная директория сохраняется
    assert (
        flussonic_timeshift_url("http://h.tv/stream/tracks-v1a1/mono.m3u8", 5)
        == "http://h.tv/stream/tracks-v1a1/timeshift_abs-5.m3u8"
    )


def test_flussonic_catchup_source_template() -> None:
    assert (
        flussonic_catchup_source("http://h.tv/stream/index.m3u8")
        == "http://h.tv/stream/timeshift_abs-{utc}.m3u8"
    )
    assert (
        flussonic_catchup_source("http://h.tv/stream/index.m3u8?ads=1")
        == "http://h.tv/stream/index.m3u8?ads=1&utc={utc}&duration={duration}"
    )


@pytest.mark.asyncio
async def test_probe_dvr_utc_query_success() -> None:
    """Первый вариант (?utc=) отвечает валидным плейлистом — один запрос."""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert "utc=" in str(request.url)
        return httpx.Response(200, text=MEDIA)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = await probe_dvr("http://h.tv/stream/playlist.m3u8", client)
    assert outcome.ok and outcome.hours == 1


@pytest.mark.asyncio
async def test_probe_dvr_falls_back_to_timeshift() -> None:
    """?utc= отдаёт 404 — пробуется timeshift_abs-<utc>.m3u8."""
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "timeshift_abs-" in str(request.url):
            return httpx.Response(200, text=MEDIA)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = await probe_dvr("http://h.tv/stream/playlist.m3u8", client)
    assert len(seen) == 2  # не более двух запросов
    assert outcome.ok and outcome.hours == 1


@pytest.mark.asyncio
async def test_probe_dvr_no_dvr() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not a playlist</html>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = await probe_dvr("http://h.tv/stream/playlist.m3u8", client)
    assert not outcome.ok and outcome.hours is None


def test_render_m3u_catchup_attributes() -> None:
    entry = M3UEntry(
        name="Канал",
        url="http://h.tv/stream/index.m3u8",
        catchup="flussonic",
        catchup_days=1,
        catchup_source="http://h.tv/stream/timeshift_abs-{utc}.m3u8",
    )
    text = render_m3u([entry])
    assert 'catchup="flussonic"' in text
    assert 'catchup-days="1"' in text
    assert 'catchup-source="http://h.tv/stream/timeshift_abs-{utc}.m3u8"' in text
    # без DVR атрибутов нет
    plain = render_m3u([M3UEntry(name="X", url="http://x/a.m3u8")])
    assert "catchup" not in plain
