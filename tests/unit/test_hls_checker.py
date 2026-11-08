"""Тесты HLS-проверки на MockTransport (без сети)."""

from __future__ import annotations

import httpx
import pytest

from iptv_monitor.checking.hls import (
    check_hls,
    parse_master_playlist,
    parse_media_playlist,
)
from iptv_monitor.domain.enums import CheckErrorCode

pytestmark = pytest.mark.usefixtures("fake_dns_guard")

MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720
720/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360
360/index.m3u8
"""

MEDIA = """#EXTM3U
#EXT-X-TARGETDURATION:6
#EXTINF:5.0,
seg00001.ts
#EXTINF:5.0,
seg00002.ts
"""


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_parse_master_playlist() -> None:
    variants = parse_master_playlist(MASTER, "https://cdn.example/live/master.m3u8")
    assert len(variants) == 2
    assert variants[0].uri == "https://cdn.example/live/720/index.m3u8"
    assert variants[0].bandwidth == 2000000
    assert variants[0].resolution == "1280x720"


def test_parse_media_playlist_segments() -> None:
    segments = parse_media_playlist(MEDIA, "https://cdn.example/live/720/index.m3u8")
    assert segments == [
        "https://cdn.example/live/720/seg00001.ts",
        "https://cdn.example/live/720/seg00002.ts",
    ]


async def test_full_hls_ok_master_media_segment() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("master.m3u8"):
            return httpx.Response(200, text=MASTER)
        if path.endswith("index.m3u8"):
            return httpx.Response(200, text=MEDIA)
        if path.endswith(".ts"):
            return httpx.Response(200, content=b"\x47" * 4096)
        return httpx.Response(404)

    async with _client(handler) as client:
        outcome = await check_hls("https://cdn.example/live/master.m3u8", client)
    assert outcome.playlist_ok is True
    assert outcome.is_master is True
    assert len(outcome.variants) == 2
    assert outcome.first_segment_ok is True
    assert outcome.error_code is None


async def test_media_playlist_direct_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("index.m3u8"):
            return httpx.Response(200, text=MEDIA)
        return httpx.Response(200, content=b"\x47" * 1024)

    async with _client(handler) as client:
        outcome = await check_hls("https://cdn.example/live/index.m3u8", client)
    assert outcome.playlist_ok is True
    assert outcome.is_master is False
    assert outcome.first_segment_ok is True


async def test_non_playlist_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not a playlist</html>")

    async with _client(handler) as client:
        outcome = await check_hls("https://cdn.example/live.m3u8", client)
    assert outcome.playlist_ok is False
    assert outcome.error_code == CheckErrorCode.HLS_INVALID


async def test_segment_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".m3u8"):
            return httpx.Response(200, text=MEDIA)
        return httpx.Response(503)

    async with _client(handler) as client:
        outcome = await check_hls("https://cdn.example/live/index.m3u8", client)
    assert outcome.playlist_ok is True
    assert outcome.first_segment_ok is not True
    assert outcome.error_code == CheckErrorCode.SEGMENT_ERROR
