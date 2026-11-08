"""Общие фикстуры тестов."""

from __future__ import annotations

from pathlib import Path

import pytest

from iptv_monitor.domain.check_result import CheckResult

FIXTURES_DIR = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def make_result():
    """Фабрика CheckResult для скоринга и хранения."""

    def _make(**kwargs) -> CheckResult:
        defaults: dict = {
            "stream_id": "stream-1",
            "probe_location": "test",
            "http_status": 200,
            "dns_ok": True,
            "playlist_ok": True,
            "first_segment_ok": True,
            "startup_time_ms": 1500,
            "width": 1920,
            "height": 1080,
        }
        defaults.update(kwargs)
        return CheckResult(**defaults)

    return _make


@pytest.fixture
def fake_dns_guard(monkeypatch):
    """Отключить реальное DNS-разрешение в SSRF-защите (офлайн-тесты)."""
    monkeypatch.setattr(
        "iptv_monitor.infrastructure.http_client.resolve_hostname",
        lambda host, port: ["93.184.216.34"],
    )
