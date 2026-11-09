"""Тесты редакции секретов в логах и URL."""

from __future__ import annotations

from iptv_monitor.infrastructure.logging import redact_query_value, redact_text, redact_url


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


# --- issue #25: единый реестр секретных ключей, Xtream username ---------


def test_xtream_username_masked_in_logs() -> None:
    """Xtream-URL: username и password маскируются в логах (username —
    учётные данные схемы Xtream)."""
    url = "http://portal.example/get.php?username=secretuser&password=secretPass1&type=m3u_plus"
    redacted = redact_url(url)
    assert "secretuser" not in redacted
    assert "secretPass1" not in redacted
    assert "username=***" in redacted
    assert "password=***" in redacted


def test_xtream_url_banned_from_publication() -> None:
    from iptv_monitor.filtering.publication_policy import url_has_secrets

    url = "http://portal.example/get.php?username=secretuser&password=secretPass1&type=m3u_plus"
    reason = url_has_secrets(url)
    assert reason is not None and "username" in reason


def test_short_tokens_in_known_keys_masked() -> None:
    """Короткие значения (8-23 символа) в известных ключах тоже маскируются."""
    assert redact_query_value("sid", "abc123") == "***"
    assert redact_query_value("st", "9f8e7d6c") == "***"
    assert redact_query_value("session", "deadbeef") == "***"


def test_single_source_of_truth() -> None:
    """Логи и политика публикации используют один реестр ключей."""
    from iptv_monitor.filtering import publication_policy
    from iptv_monitor.infrastructure import logging as redaction_logging
    from iptv_monitor.infrastructure.secrets import TOKEN_KEYS

    # Списки больше не дублируются: оба модуля ссылаются на один объект
    assert publication_policy.TOKEN_KEYS is TOKEN_KEYS
    assert redaction_logging.TOKEN_KEYS is TOKEN_KEYS
