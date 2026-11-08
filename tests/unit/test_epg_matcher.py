"""Тесты сопоставления EPG (tvg-id, алиасы, нормализованные имена)."""

from __future__ import annotations

from iptv_monitor.domain.channel import Channel
from iptv_monitor.domain.enums import MatchMethod
from iptv_monitor.metadata import AliasIndex, match_epg, parse_xmltv
from iptv_monitor.metadata.epg.parser import EpgChannelData
from iptv_monitor.settings import AliasRule


def _channel(name: str, tvg_id: str | None = None, alt: list[str] | None = None) -> Channel:
    return Channel(
        channel_id=f"ru-{name.lower().replace(' ', '-')}",
        name=name,
        country="RU",
        tvg_id=tvg_id,
        alt_names=alt or [],
    )


EPG = [
    EpgChannelData(id="1tv.ru", display_names=["Первый канал", "Первый"]),
    EpgChannelData(id="matchtv.ru", display_names=["Матч ТВ", "Матч!"]),
    EpgChannelData(id="5-tv.ru", display_names=["Пятый канал"]),
]


def test_exact_tvg_id_match() -> None:
    matches = match_epg([_channel("Первый", tvg_id="1tv.ru")], EPG, AliasIndex([]))
    assert len(matches) == 1
    assert matches[0].method == MatchMethod.TVG_ID
    assert matches[0].confidence == 1.0
    assert matches[0].manual is False


def test_manual_alias_wins_over_name() -> None:
    # Без алиаса канал «Первый» сопоставляется по нормализованному имени.
    baseline = match_epg([_channel("Первый")], EPG, AliasIndex([]))
    assert baseline and baseline[0].method == MatchMethod.NORMALIZED_NAME

    aliases = AliasIndex([AliasRule(name="Первый", tvg_id="alias-1tv.ru", manual=True)])
    matches = match_epg([_channel("Первый")], EPG, aliases)
    assert len(matches) == 1
    assert matches[0].method == MatchMethod.ALIAS
    assert matches[0].tvg_id == "alias-1tv.ru"
    assert matches[0].manual is True


def test_normalized_name_match_with_alt_names() -> None:
    matches = match_epg([_channel("Спорт канал", alt=["Матч ТВ HD"])], EPG, AliasIndex([]))
    assert len(matches) == 1
    assert matches[0].method == MatchMethod.NORMALIZED_NAME
    assert matches[0].tvg_id == "matchtv.ru"


def test_unmatched_channel_has_no_match() -> None:
    matches = match_epg([_channel("Неизвестный канал")], EPG, AliasIndex([]))
    assert matches == []


def test_xmltv_fixture_parses() -> None:
    text = open("tests/fixtures/ru_sample.xmltv", encoding="utf-8").read()
    channels, programmes = parse_xmltv(text)
    assert len(channels) == 3
    assert len(programmes) == 2  # запись с битым временем пропущена
    assert programmes[0].title == "Новости"
