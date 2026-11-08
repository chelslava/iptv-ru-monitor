"""Тесты классификации категорий и дедупликации."""

from __future__ import annotations

from iptv_monitor.domain.channel import Channel
from iptv_monitor.domain.enums import Category
from iptv_monitor.domain.stream import Stream, make_stream_id
from iptv_monitor.normalization.categories import classify_channel
from iptv_monitor.normalization.deduplication import deduplicate, merge_key
from iptv_monitor.settings import CategoryRule

RULES = [
    CategoryRule(category=Category.NEWS, patterns=["новост", "news"]),
    CategoryRule(category=Category.KIDS, patterns=["детск", "мульт", "карусел"]),
    CategoryRule(category=Category.SPORTS, patterns=["спорт", "матч"]),
]


def _rule_list() -> list[CategoryRule]:
    return [rule.model_copy() for rule in RULES]


def test_classify_by_name() -> None:
    assert (
        classify_channel(name="Новости 24", group_title=None, rules=_rule_list()) == Category.NEWS
    )


def test_classify_by_group() -> None:
    assert (
        classify_channel(name="Неизвестное название", group_title="Детские", rules=_rule_list())
        == Category.KIDS
    )


def test_classify_falls_back_to_default() -> None:
    assert (
        classify_channel(name="Что-то", group_title="Разное", rules=_rule_list())
        == Category.GENERAL
    )


def _channel(channel_id: str, name: str, **kwargs: object) -> Channel:
    return Channel(channel_id=channel_id, name=name, country="RU", **kwargs)  # type: ignore[arg-type]


def test_merge_key_ignores_quality() -> None:
    assert merge_key(_channel("a", "Канал HD")) == merge_key(_channel("b", "Канал"))


def test_deduplicate_merges_channels_and_streams() -> None:
    # Каналы «Канал» и «Канал HD» — одна сущность; первичным становится
    # вариант с tvg_id.
    channels = [
        _channel("ru-kanal-1", "Канал", tvg_id="kanal.ru", is_public=True),
        _channel("ru-kanal-2", "Канал HD", is_public=False),
    ]
    streams = [
        Stream(
            stream_id=make_stream_id("https://a.example/1.m3u8"),
            channel_id="ru-kanal-1",
            url="https://a.example/1.m3u8",
            protocol="hls",
            source_id="src",
        ),
        Stream(
            stream_id=make_stream_id("https://b.example/1.m3u8"),
            channel_id="ru-kanal-2",
            url="https://b.example/1.m3u8",
            protocol="hls",
            source_id="src",
        ),
        # Дубликат URL — должен быть отброшен.
        Stream(
            stream_id=make_stream_id("https://a.example/1.m3u8"),
            channel_id="ru-kanal-2",
            url="https://a.example/1.m3u8",
            protocol="hls",
            source_id="src2",
        ),
    ]

    merged_channels, merged_streams = deduplicate(channels, streams)

    assert len(merged_channels) == 1
    primary = merged_channels[0]
    assert primary.channel_id == "ru-kanal-1"  # вариант с tvg_id выигрывает
    assert primary.tvg_id == "kanal.ru"
    assert "Канал HD" in primary.alt_names
    assert primary.is_public is False  # консервативно: все варианты должны быть публичными

    assert len(merged_streams) == 2
    assert {s.channel_id for s in merged_streams} == {"ru-kanal-1"}
    assert {s.url for s in merged_streams} == {
        "https://a.example/1.m3u8",
        "https://b.example/1.m3u8",
    }
