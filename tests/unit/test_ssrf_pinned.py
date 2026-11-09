"""Pinned-бэкенд против DNS-rebinding и guard субпроцессов (issue #23)."""

from __future__ import annotations

import httpx
import pytest

from iptv_monitor.checking.scheduler import check_stream
from iptv_monitor.domain.enums import CheckErrorCode, StreamProtocol
from iptv_monitor.domain.stream import Stream, make_stream_id
from iptv_monitor.infrastructure.http_client import (
    UrlGuardError,
    create_client,
    fetch,
)
from iptv_monitor.settings import AppSettings


@pytest.fixture
def rebind_dns(monkeypatch):
    """DNS-ребиндинг: имя валидно для validate_url, но пиннинг-бэкенд видит
    свежее разрешение на приватный IP — соединение должно быть запрещено."""
    calls = {"n": 0}

    def resolve(host, port):
        calls["n"] += 1
        # Первый вызов (validate_url в fetch) — публичный IP; второй
        # (pinned backend в момент connect) — приватный, как реальный
        # rebinding между проверкой и соединением.
        return ["93.184.216.34"] if calls["n"] == 1 else ["10.1.2.3"]

    monkeypatch.setattr("iptv_monitor.infrastructure.http_client.resolve_hostname", resolve)
    return calls


async def test_rebinding_blocked_at_connect(rebind_dns) -> None:
    """Пиннинг-бэкенд запрещает соединение с приватным IP после валидации.

    fetch(): validate_url разрешил публичный IP (вызов 1), но к моменту
    TCP-соединения DNS перебиндился на приватный (вызов 2) — соединение
    запрещено, к приватному адресу ничего не подключается.
    """
    async with create_client() as client:
        result = await fetch(client, "https://rebind.example/live.m3u8")
    assert rebind_dns["n"] == 2  # валидация + пиннинг в момент соединения
    assert result.error_code == CheckErrorCode.TRANSPORT_ERROR
    assert result.dns_ok is True  # предварительная валидация прошла


def _stream(url: str) -> Stream:
    return Stream(
        stream_id=make_stream_id(url),
        channel_id="ru-test",
        url=url,
        protocol=StreamProtocol.HTTP,
        source_id="test",
    )


@pytest.mark.usefixtures("fake_dns_guard")
async def test_ffprobe_url_guard_blocks(monkeypatch) -> None:
    """Guard перед запуском ffprobe: запрещённый URL не доходит до субпроцесса."""

    async def must_not_run(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("ffprobe must not be invoked for forbidden URLs")

    async def guard(url):
        raise UrlGuardError(url, "forbidden ip range", CheckErrorCode.SSRF_BLOCKED)

    monkeypatch.setattr("iptv_monitor.checking.scheduler.probe_media", must_not_run)
    monkeypatch.setattr("iptv_monitor.checking.scheduler.validate_url", guard)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 4096)  # уровень 1 проходит

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await check_stream(
            _stream("https://ok.example/live.ts"), client, AppSettings(), levels=("ffprobe",)
        )
    assert result.error_code == CheckErrorCode.SSRF_BLOCKED
    assert result.video_codec is None  # ffprobe не вызывался


@pytest.mark.usefixtures("fake_dns_guard")
async def test_ffprobe_dns_failure_reported(monkeypatch) -> None:
    """Неразрешимый URL: guard возвращает dns_error до запуска ffprobe."""

    async def must_not_run(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("ffprobe must not be invoked for dead dns")

    async def guard(url):
        raise UrlGuardError(url, "dns resolution failed", CheckErrorCode.DNS_ERROR)

    monkeypatch.setattr("iptv_monitor.checking.scheduler.probe_media", must_not_run)
    monkeypatch.setattr("iptv_monitor.checking.scheduler.validate_url", guard)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 4096)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await check_stream(
            _stream("https://dead.example/live.ts"), client, AppSettings(), levels=("ffprobe",)
        )
    assert result.error_code == CheckErrorCode.DNS_ERROR
