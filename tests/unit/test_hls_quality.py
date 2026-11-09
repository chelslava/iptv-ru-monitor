"""Качество HLS-проверки (issue #24): вариант, sniffing, retry, DVR, пустой плейлист."""

from __future__ import annotations

import httpx
import pytest

from iptv_monitor.checking.hls import (
    HlsVariant,
    check_hls,
    looks_like_media_bytes,
    parse_variant_height,
    probe_dvr,
    select_variant,
)
from iptv_monitor.checking.scheduler import check_stream
from iptv_monitor.domain.enums import CheckErrorCode, StreamProtocol
from iptv_monitor.domain.stream import Stream, make_stream_id
from iptv_monitor.settings import AppSettings

pytestmark = pytest.mark.usefixtures("fake_dns_guard")


def test_select_variant_picks_lowest_bandwidth() -> None:
    variants = [
        HlsVariant(uri="https://a.example/hi.m3u8", bandwidth=4_000_000),
        HlsVariant(uri="https://a.example/lo.m3u8", bandwidth=500_000),
        HlsVariant(uri="https://a.example/mid.m3u8", bandwidth=1_500_000),
    ]
    assert select_variant(variants).uri == "https://a.example/lo.m3u8"


def test_parse_variant_height() -> None:
    assert parse_variant_height("1280x720") == 720
    assert parse_variant_height("1920x1080") == 1080
    assert parse_variant_height(None) is None
    assert parse_variant_height("garbage") is None


@pytest.mark.parametrize(
    "body",
    [
        b"\x47\x40\x00\x10" + b"\x00" * 184,  # MPEG-TS
        b"\x00\x00\x00\x18ftypiso5",  # fMP4
        b"\xff\xf1\x50\x80",  # ADTS AAC
        b"ID3\x04\x00",  # MP3 c ID3
        b"\x1aE\xdf\xa3" + b"\x00" * 16,  # EBML
    ],
)
def test_media_bytes_accepted(body: bytes) -> None:
    assert looks_like_media_bytes(body)


@pytest.mark.parametrize(
    "body",
    [
        b"<html><body>502 Bad Gateway</body></html>",
        b"",
        b"\x00\x00\x00\x00",
        b"Range not satisfiable",
    ],
)
def test_garbage_bytes_rejected(body: bytes) -> None:
    assert not looks_like_media_bytes(body)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


MASTER = (
    "#EXTM3U\n"
    '#EXT-X-STREAM-INF:BANDWIDTH=4000000,RESOLUTION="1920x1080"\n'
    "hi.m3u8\n"
    '#EXT-X-STREAM-INF:BANDWIDTH=500000,RESOLUTION="640x360"\n'
    "lo.m3u8\n"
)
MEDIA = "#EXTM3U\n#EXTINF:6.0,\nseg0.ts\n"
TS = b"\x47" + b"\x00" * 187


async def test_variant_selection_and_declared_params() -> None:
    """Минимальный bandwidth выбран; declared_height из его RESOLUTION."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("lo.m3u8"):
            return httpx.Response(200, text=MEDIA)
        if request.url.path.endswith("seg0.ts"):
            return httpx.Response(200, content=TS)
        return httpx.Response(200, text=MASTER)

    async with _client(handler) as client:
        outcome = await check_hls("https://hls.example/master.m3u8", client)
    assert outcome.media_url == "https://hls.example/lo.m3u8"
    assert outcome.declared_height == 360
    assert outcome.declared_bandwidth == 500_000
    assert outcome.first_segment_ok is True


async def test_html_segment_rejected_by_sniffing() -> None:
    """Сегмент с HTML-телом (сервер игнорирует Range) — segment_error."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("seg0.ts"):
            return httpx.Response(200, text="<html>error page</html>")
        return httpx.Response(200, text=MEDIA)

    async with _client(handler) as client:
        outcome = await check_hls("https://hls.example/media.m3u8", client)
    assert outcome.error_code == CheckErrorCode.SEGMENT_ERROR
    assert outcome.first_segment_ok is None


async def test_empty_playlist_is_playlist_empty() -> None:
    """Плейлист без сегментов — playlist_empty, а не успех HLS."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="#EXTM3U\n#EXT-X-TARGETDURATION:6\n")

    async with _client(handler) as client:
        outcome = await check_hls("https://hls.example/media.m3u8", client)
    assert outcome.playlist_ok is True
    assert outcome.error_code == CheckErrorCode.PLAYLIST_EMPTY


async def test_transient_timeout_retried() -> None:
    """timeout -> один повтор -> успех; результат помечен retried."""
    timeouts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if timeouts["n"] == 0:
            timeouts["n"] += 1  # только первая попытка уровня HTTP
            raise httpx.ConnectTimeout("transient")
        if request.url.path.endswith(".ts"):
            return httpx.Response(200, content=TS)
        return httpx.Response(
            200, headers={"content-type": "application/vnd.apple.mpegurl"}, content=MEDIA.encode()
        )

    url = "https://flaky.example/live.m3u8"
    stream = Stream(
        stream_id=make_stream_id(url),
        channel_id="ru-test",
        url=url,
        protocol=StreamProtocol.HLS,
        source_id="test",
    )
    async with _client(handler) as client:
        result = await check_stream(stream, client, AppSettings())
    assert result.error_code is None
    assert result.retried is True
    assert result.playlist_ok is True
    assert timeouts["n"] == 1  # один повтор, не бесконечный


async def test_persistent_timeout_single_retry() -> None:
    """Стабильно таймаутящий поток: один повтор, итог — timeout."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectTimeout("still down")

    url = "https://down.example/live.m3u8"
    stream = Stream(
        stream_id=make_stream_id(url),
        channel_id="ru-test",
        url=url,
        protocol=StreamProtocol.HLS,
        source_id="test",
    )
    async with _client(handler) as client:
        result = await check_stream(stream, client, AppSettings())
    assert result.error_code == CheckErrorCode.TIMEOUT
    assert result.retried is True
    assert calls["n"] == 2  # один повтор, не бесконечный


async def test_dvr_ignoring_utc_is_not_dvr() -> None:
    """Сервер отдаёт одинаковый плейлист с utc и без — архива нет (issue #24)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=MEDIA)

    async with _client(handler) as client:
        outcome = await probe_dvr("https://flus.example/live/mono.m3u8", client)
    assert outcome.ok is False


async def test_dvr_with_real_archive() -> None:
    """utc-плейлист отличается от live — архив подтверждён."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "utc=" in str(request.url):
            return httpx.Response(200, text=MEDIA.replace("seg0.ts", "old-seg0.ts"))
        return httpx.Response(200, text=MEDIA)

    async with _client(handler) as client:
        outcome = await probe_dvr("https://flus.example/live/mono.m3u8", client)
    assert outcome.ok is True
    assert outcome.hours == 1
