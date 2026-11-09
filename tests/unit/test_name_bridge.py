"""Тесты моста имён iptv-org/database (issue #5)."""

from __future__ import annotations

from iptv_monitor.domain.channel import Channel
from iptv_monitor.domain.enums import MatchMethod
from iptv_monitor.metadata import AliasIndex, match_epg, parse_channels_csv
from iptv_monitor.metadata.epg.parser import EpgChannelData
from iptv_monitor.settings import NameBridgeSettings

# Фрагмент channels.csv iptv-org/database: имя с запятой в кавычках,
# alt_names через «;», включая русские. Строки длинные намеренно — так
# выглядит реальный файл.
# ruff: noqa: E501
CSV = """id,name,alt_names,network,owners,country,categories,is_nsfw,launched,closed,replaced_by,website
ChannelOne.ru,"Channel One",Первый канал;Pervyy Kanal;Channel 1 Ostankino,,Government of the Russian Federation,RU,general,FALSE,2002-09-01,,,https://www.1tv.ru/
2x2.ru,2x2,Дважды два,,Gazprom Media,RU,entertainment,FALSE,2018-04-11,,,https://2x2tv.ru/
matchtv.ru,"Match, Match! TV",Матч ТВ,,,RU,sports,FALSE,,,,https://matchtv.ru/
broken.ru,,,
"""


def test_parse_channels_csv() -> None:
    bridge = parse_channels_csv(CSV)
    assert len(bridge) == 3  # broken.ru без имени отброшен
    names = bridge.names_for("ChannelOne.ru@SD")
    assert names[0] == "Channel One"
    assert "Первый канал" in names
    assert "Channel 1 Ostankino" in names


def test_names_for_strips_feed_suffix() -> None:
    bridge = parse_channels_csv(CSV)
    # суффикс фида @SD/@HD отделяется, id без фида тоже работает
    assert bridge.names_for("2x2.ru@HD") == ["2x2", "Дважды два"]
    assert bridge.names_for("2x2.ru") == ["2x2", "Дважды два"]


def test_names_for_unknown_and_empty() -> None:
    bridge = parse_channels_csv(CSV)
    # числовой id epg.pw и None не мостятся — только iptv-org id
    assert bridge.names_for("7103") == []
    assert bridge.names_for(None) == []
    assert bridge.names_for("") == []


def test_names_with_comma_in_quotes() -> None:
    bridge = parse_channels_csv(CSV)
    assert bridge.names_for("matchtv.ru@SD")[0] == "Match, Match! TV"
    assert "Матч ТВ" in bridge.names_for("matchtv.ru")


def _epg() -> list[EpgChannelData]:
    return [EpgChannelData(id="5735", display_names=["Первый канал"])]


def test_bridge_matches_via_database_names() -> None:
    """Канал с EN-именем, унаследованным от iptv-org, находит RU-канал EPG."""
    channels = [
        Channel(
            channel_id="ru-chn-one",
            name="Channel One (1080p)",
            country="RU",
            tvg_id="ChannelOne.ru@SD",
        ),
    ]
    matches = match_epg(channels, _epg(), AliasIndex([]), bridge=parse_channels_csv(CSV))
    assert len(matches) == 1
    assert matches[0].tvg_id == "5735"
    assert matches[0].method == MatchMethod.BRIDGE
    assert matches[0].original_name == "Первый канал"


def test_own_name_beats_bridge() -> None:
    """Собственное имя приоритетнее моста даже если мост ведёт на другой id."""
    channels = [
        Channel(channel_id="ru-two", name="Первый канал", country="RU", tvg_id="ChannelOne.ru@SD"),
    ]
    epg = [
        EpgChannelData(id="5735", display_names=["Первый канал"]),
        EpgChannelData(id="9999", display_names=["Channel One"]),
    ]
    matches = match_epg(channels, epg, AliasIndex([]), bridge=parse_channels_csv(CSV))
    assert matches[0].tvg_id == "5735"
    assert matches[0].method == MatchMethod.NORMALIZED_NAME


def test_without_bridge_no_match() -> None:
    """Без моста тот же канал остаётся без сопоставления (обратная совместимость)."""
    channels = [
        Channel(
            channel_id="ru-chn-one",
            name="Channel One (1080p)",
            country="RU",
            tvg_id="ChannelOne.ru@SD",
        ),
    ]
    matches = match_epg(channels, _epg(), AliasIndex([]))
    assert matches == []


def test_name_bridge_settings_default() -> None:
    cfg = NameBridgeSettings.model_validate({})
    assert cfg.enabled is False
    assert cfg.url.endswith("channels.csv")
