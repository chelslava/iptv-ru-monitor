"""Тесты политики публикации."""

from __future__ import annotations

from iptv_monitor.domain.channel import Channel
from iptv_monitor.domain.source import SourceConfig
from iptv_monitor.domain.stream import Stream, make_stream_id
from iptv_monitor.filtering import decide_publication, load_approved_ids, url_has_secrets


def _channel(**kwargs: object) -> Channel:
    defaults: dict = {"channel_id": "ru-x", "name": "Канал", "country": "RU", "is_public": True}
    defaults.update(kwargs)
    return Channel(**defaults)  # type: ignore[arg-type]


def _stream(url: str = "https://ok.example/stream.m3u8") -> Stream:
    return Stream(
        stream_id=make_stream_id(url),
        channel_id="ru-x",
        url=url,
        protocol="hls",
        source_id="src-allow",
    )


def _source(policy: str) -> SourceConfig:
    return SourceConfig(id="src-allow", adapter="custom_m3u", public_policy=policy, country="RU")


def test_url_secret_detection() -> None:
    assert url_has_secrets("https://x.example/s.m3u8?token=abc") is not None
    assert url_has_secrets("https://x.example/s.m3u8?key=value") is not None
    assert url_has_secrets("https://user:pass@x.example/s.m3u8") is not None
    long_token = "a" * 32
    assert url_has_secrets(f"https://x.example/s.m3u8?sig={long_token}") is not None
    assert url_has_secrets("https://x.example/s.m3u8?id=42&v=7") is None


def test_allow_policy_with_clean_url() -> None:
    decision = decide_publication(_channel(), _stream(), _source("allow"))
    assert decision.allowed, decision.reasons


def test_review_requires_approval() -> None:
    stream = _stream()
    decision = decide_publication(_channel(), stream, _source("review"))
    assert not decision.allowed
    assert any("approval" in r for r in decision.reasons)

    decision = decide_publication(_channel(), stream, _source("review"), {stream.stream_id})
    assert decision.allowed


def test_approved_review_overrides_non_public_channel() -> None:
    # Реальный кейс: review-источник => channel.is_public=False, но
    # подтверждение stream_id и есть допуск к публикации.
    stream = _stream()
    decision = decide_publication(
        _channel(is_public=False), stream, _source("review"), {stream.stream_id}
    )
    assert decision.allowed, decision.reasons


def test_deny_policy_never_publishes() -> None:
    decision = decide_publication(_channel(), _stream(), _source("deny"))
    assert not decision.allowed
    assert any("denies" in r for r in decision.reasons)


def test_secret_url_blocks_even_allow() -> None:
    url = "https://ok.example/stream.m3u8?token=verysecretvalue123"
    decision = decide_publication(_channel(), _stream(url), _source("allow"))
    assert not decision.allowed
    assert any("secret" in r for r in decision.reasons)


def test_non_public_channel_blocked() -> None:
    decision = decide_publication(_channel(is_public=False), _stream(), _source("allow"))
    assert not decision.allowed


def test_unknown_source_blocked() -> None:
    decision = decide_publication(_channel(), _stream(), None)
    assert not decision.allowed


def test_load_approved_ids(tmp_path) -> None:
    target = tmp_path / "approved_streams.yaml"
    target.write_text("stream_ids:\n  - abc\n  - def\n", encoding="utf-8")
    assert load_approved_ids(tmp_path) == {"abc", "def"}
    assert load_approved_ids(tmp_path / "missing") == set()
