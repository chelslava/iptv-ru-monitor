"""Тесты определения страны по tvg-id/названию и очистки имён."""

from __future__ import annotations

from iptv_monitor.discovery import DiscoveredStream
from iptv_monitor.domain.source import SourceConfig
from iptv_monitor.normalization import normalize_discovered
from iptv_monitor.normalization.channel_names import clean_display_name
from iptv_monitor.normalization.country import (
    country_from_name,
    country_from_tvg_id,
    detect_country,
)
from iptv_monitor.settings import CategoriesFile


def test_country_from_tvg_id() -> None:
    assert country_from_tvg_id("1tv.ru") == "RU"
    assert country_from_tvg_id("2x2.ru@SD") == "RU"
    assert country_from_tvg_id("ChannelOne.ru") == "RU"
    assert country_from_tvg_id("bbcone.uk") == "GB"
    assert country_from_tvg_id("Milliy.uz") == "UZ"
    assert country_from_tvg_id("Match") is None
    assert country_from_tvg_id(None) is None
    assert country_from_tvg_id("x.yy") is None  # неизвестный код


def test_country_from_name() -> None:
    assert country_from_name("Milliy TV UZ") == "UZ"
    assert country_from_name("Канал (KZ)") == "KZ"
    assert country_from_name("Первый канал") is None
    assert country_from_name("Матч ТВ") is None
    # «US Open» — турнир, а не страна (issue #15)
    assert country_from_name("US Open (1080p)") is None
    assert country_from_name("EU Cup", group_title=None) is None
    assert country_from_name("US Weekly") is None
    assert country_from_name(None) is None


def test_country_group_beats_name() -> None:
    """Группа надёжнее имени при конфликте кодов (issue #15)."""
    assert country_from_name("News US", group_title="Общество") == "US"
    assert country_from_name("News US", group_title="Regional DE") == "DE"
    # событие в имени, страна в группе — группа побеждает
    assert country_from_name("US Open Tennis", group_title="Sports RU") == "RU"


def test_detect_country_priority() -> None:
    # tvg-id надёжнее названия и страны источника
    assert (
        detect_country(
            tvg_id="x.uz",
            entry_country=None,
            name="Что-то",
            group_title=None,
            source_country="RU",
        )
        == "UZ"
    )
    # название надёжнее страны источника (агрегаторы смешанного контента)
    assert (
        detect_country(
            tvg_id=None,
            entry_country=None,
            name="Milliy TV UZ",
            group_title=None,
            source_country="RU",
        )
        == "UZ"
    )
    # fallback на страну источника
    assert (
        detect_country(
            tvg_id=None,
            entry_country=None,
            name="Россия 1",
            group_title="Общие",
            source_country="RU",
        )
        == "RU"
    )


def test_clean_display_name() -> None:
    assert clean_display_name("Матч ТВ Ⓢ") == "Матч ТВ"
    assert clean_display_name("НТВ Ⓢ ") == "НТВ"
    assert clean_display_name("365 days TV (576p)") == "365 days TV (576p)"
    assert clean_display_name("86 (1080p) [Not 24/7]") == "86 (1080p) [Not 24/7]"


def _source() -> SourceConfig:
    return SourceConfig(id="src", adapter="remote_m3u", country="RU", public_policy="review")


def _entry(name: str, url: str, tvg_id: str | None = None) -> DiscoveredStream:
    return DiscoveredStream(source_id="src", name=name, url=url, tvg_id=tvg_id)


def test_normalize_splits_countries_in_mixed_source() -> None:
    entries = [
        _entry("Россия 1", "https://s.example/r1.m3u8", "Russia1.ru"),
        _entry("Milliy TV UZ", "https://s.example/milliy.m3u8"),
        _entry("Первый", "https://s.example/1tv.m3u8"),
    ]
    categories = CategoriesFile(rules=[])
    channels, streams = normalize_discovered(entries, [_source()], categories)
    by_name = {c.name: c.country for c in channels}
    assert by_name["Россия 1"] == "RU"
    assert by_name["Milliy TV UZ"] == "UZ"  # не наследует RU от источника
    assert by_name["Первый"] == "RU"  # fallback на страну источника
    assert len(streams) == 3


def test_normalize_cleans_markers_in_names() -> None:
    entries = [_entry("Матч ТВ Ⓢ", "https://s.example/match.m3u8", "Match.ru")]
    channels, _ = normalize_discovered(entries, [_source()], CategoriesFile(rules=[]))
    assert channels[0].name == "Матч ТВ"
