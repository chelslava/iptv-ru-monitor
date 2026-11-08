"""Тесты редакции секретов в логах и URL."""

from __future__ import annotations

from iptv_monitor.infrastructure.logging import redact_text, redact_url


def test_redact_url_masks_token_parameter() -> None:
    url = "https://stream.example.org/s.m3u8?token=abc123def456ghi789"
    masked = redact_url(url)
    assert "abc123def456ghi789" not in masked
    assert "token=***" in masked


def test_redact_url_keeps_normal_parameters() -> None:
    url = "https://stream.example.org/s.m3u8?id=42"
    assert redact_url(url) == url


def test_redact_url_without_query_untouched() -> None:
    url = "https://stream.example.org/s.m3u8"
    assert redact_url(url) == url


def test_redact_text_rewrites_urls_in_message() -> None:
    message = "stream failed: https://x.example/a.m3u8?auth=supersecretvalue after redirect"
    masked = redact_text(message)
    assert "supersecretvalue" not in masked
    assert "auth=***" in masked
    assert masked.startswith("stream failed:")
