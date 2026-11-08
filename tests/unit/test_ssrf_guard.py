"""Тесты SSRF-защиты."""

from __future__ import annotations

import ipaddress

import pytest

from iptv_monitor.domain.enums import CheckErrorCode
from iptv_monitor.infrastructure.http_client import (
    UrlGuardError,
    is_forbidden_ip,
    validate_url_sync,
)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.1",
        "192.168.1.1",
        "172.16.0.5",
        "169.254.169.254",  # metadata-сервис облачных провайдеров
        "100.64.0.1",  # carrier-grade NAT
        "0.0.0.0",
        "::1",
        "fc00::1",
        "fe80::1",
    ],
)
def test_forbidden_ips(ip: str) -> None:
    assert is_forbidden_ip(ipaddress.ip_address(ip))


@pytest.mark.parametrize("ip", ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"])
def test_public_ips_allowed(ip: str) -> None:
    assert not is_forbidden_ip(ipaddress.ip_address(ip))


def test_literal_private_ip_blocked() -> None:
    with pytest.raises(UrlGuardError) as excinfo:
        validate_url_sync("http://192.168.0.1:8080/secret")
    assert excinfo.value.error_code == CheckErrorCode.SSRF_BLOCKED


def test_localhost_blocked() -> None:
    with pytest.raises(UrlGuardError) as excinfo:
        validate_url_sync("http://localhost/x")
    assert excinfo.value.error_code == CheckErrorCode.SSRF_BLOCKED


def test_unsupported_scheme_rejected() -> None:
    with pytest.raises(UrlGuardError) as excinfo:
        validate_url_sync("ftp://example.org/file")
    assert excinfo.value.error_code == CheckErrorCode.UNSUPPORTED_SCHEME


def test_public_host_allowed(monkeypatch) -> None:
    monkeypatch.setattr(
        "iptv_monitor.infrastructure.http_client.resolve_hostname",
        lambda host, port: ["93.184.216.34"],
    )
    assert validate_url_sync("https://stream.example.org/live.m3u8") == ["93.184.216.34"]


def test_dns_failure_classified(monkeypatch) -> None:
    import socket

    def _fail(host: str, port: int) -> list[str]:
        raise socket.gaierror("no such host")

    monkeypatch.setattr("iptv_monitor.infrastructure.http_client.resolve_hostname", _fail)
    with pytest.raises(UrlGuardError) as excinfo:
        validate_url_sync("https://nonexistent.example.org/live.m3u8")
    assert excinfo.value.error_code == CheckErrorCode.DNS_ERROR
