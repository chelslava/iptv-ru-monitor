"""UA-fallback: 403 с плеерным UA — не мёртвый поток (issue #18)."""

from __future__ import annotations

import httpx
import pytest

from iptv_monitor.checking.scheduler import check_stream
from iptv_monitor.domain.enums import CheckErrorCode, StreamProtocol
from iptv_monitor.domain.stream import Stream, make_stream_id
from iptv_monitor.settings import AppSettings

pytestmark = pytest.mark.usefixtures("fake_dns_guard")

BROWSER_UA = AppSettings().check.browser_user_agent


def _stream() -> Stream:
    url = "https://ua-block.example/live.m3u8"
    return Stream(
        stream_id=make_stream_id(url),
        channel_id="ru-test",
        url=url,
        protocol=StreamProtocol.HLS,
        source_id="test",
    )


MEDIA = "#EXTM3U\n#EXTINF:6.0,\nseg0.ts\n"
TS = b"\x47" + b"\x00" * 187


def _handler_blocker(request: httpx.Request) -> httpx.Response:
    if request.headers.get("user-agent") == BROWSER_UA:
        if request.url.path.endswith(".ts"):
            return httpx.Response(200, content=TS)
        return httpx.Response(
            200, headers={"content-type": "application/vnd.apple.mpegurl"}, content=MEDIA.encode()
        )
    return httpx.Response(403, text="forbidden")


async def test_403_recovered_with_browser_ua() -> None:
    """403 плеерному UA + 200 браузерному = успех с ua_required=True."""
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler_blocker)) as client:
        result = await check_stream(_stream(), client, AppSettings())
    assert result.error_code is None
    assert result.ua_required is True
    assert result.http_status == 200


async def test_403_persists_without_fallback() -> None:
    """403 и с браузерным UA — обычный http_4xx, ua_required=False."""
    settings = AppSettings()
    settings.check.ua_fallback = False

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await check_stream(_stream(), client, settings)
    assert result.error_code == CheckErrorCode.HTTP_4XX
    assert result.ua_required is False


async def test_403_still_blocked_with_browser_ua() -> None:
    """403 для любого UA — остаётся http_4xx (не маскируем реальный запрет)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await check_stream(_stream(), client, AppSettings())
    assert result.error_code == CheckErrorCode.HTTP_4XX
    assert result.ua_required is False


async def test_success_without_403_no_fallback() -> None:
    """Fallback только для 401/403/444: обычный 200 не дёргает повторный запрос."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if request.url.path.endswith(".ts"):
            return httpx.Response(200, content=b"\x47" + b"\x00" * 187)
        return httpx.Response(
            200,
            headers={"content-type": "application/vnd.apple.mpegurl"},
            content=b"#EXTM3U\n#EXTINF:6.0,\nseg0.ts\n",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        settings = AppSettings()
        result = await check_stream(_stream(), client, settings)
    assert result.error_code is None
    assert calls["n"] >= 1
    assert result.ua_required is False
