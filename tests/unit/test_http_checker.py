"""Тесты HTTP-проверки на MockTransport (без сети)."""

from __future__ import annotations

import httpx
import pytest

from iptv_monitor.checking import classify_http
from iptv_monitor.domain.enums import CheckErrorCode
from iptv_monitor.infrastructure.http_client import fetch

pytestmark = pytest.mark.usefixtures("fake_dns_guard")


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_successful_fetch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "application/vnd.apple.mpegurl"}, content=b"#EXTM3U\n"
        )

    async with _client(handler) as client:
        result = await fetch(client, "https://ok.example/live.m3u8", max_bytes=1024)
    assert result.ok
    assert result.status == 200
    assert result.dns_ok is True
    assert result.body.startswith(b"#EXTM3U")
    code, _ = classify_http(result)
    assert code is None


async def test_403_classified_as_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    async with _client(handler) as client:
        result = await fetch(client, "https://geo.example/live.m3u8")
    code, message = classify_http(result)
    assert code == CheckErrorCode.HTTP_4XX
    assert "403" in (message or "")


async def test_redirect_to_private_ip_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://192.168.0.1/internal"})

    # Реальная проверка литерального IP работает и без fake_dns_guard.
    async with _client(handler) as client:
        result = await fetch(client, "https://evil.example/live.m3u8")
    assert result.error_code == CheckErrorCode.SSRF_BLOCKED


async def test_redirect_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": str(request.url)})

    async with _client(handler) as client:
        result = await fetch(client, "https://loop.example/live.m3u8", max_redirects=3)
    assert result.error_code == CheckErrorCode.REDIRECT_LIMIT


async def test_timeout_classified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    async with _client(handler) as client:
        result = await fetch(client, "https://slow.example/live.m3u8")
    assert result.error_code == CheckErrorCode.TIMEOUT


async def test_body_limited() -> None:
    huge = b"x" * 1_000_000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=huge)

    async with _client(handler) as client:
        result = await fetch(client, "https://big.example/live.ts", max_bytes=65536)
    assert len(result.body) <= 65536


async def test_redirect_without_location_is_terminal() -> None:
    """Редирект без Location — терминальный ответ, а не TypeError/цикл (issue #19)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302)  # заголовка location нет

    async with _client(handler) as client:
        result = await fetch(client, "https://broken.example/live.m3u8")
    assert result.error_code == CheckErrorCode.REDIRECT_INVALID
    assert "without location" in (result.error_message or "")


async def test_redirect_with_empty_location_is_terminal() -> None:
    """Пустой Location тоже не должен зацикливать fetch (issue #19)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": ""})

    async with _client(handler) as client:
        result = await fetch(client, "https://empty.example/live.m3u8")
    assert result.error_code == CheckErrorCode.REDIRECT_INVALID
