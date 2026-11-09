"""Тесты мультиисточникового EPG: декодирование, два прохода, неймспейс (#5)."""

from __future__ import annotations

import gzip

from iptv_monitor.domain.channel import Channel
from iptv_monitor.domain.enums import MatchMethod
from iptv_monitor.metadata import AliasIndex, match_epg
from iptv_monitor.metadata.epg.parser import (
    decode_xmltv,
    namespace_epg,
    parse_xmltv_channels,
    parse_xmltv_programmes,
)

XML = (
    "<?xml version='1.0' encoding='windows-1251'?>\n<tv>"
    "<channel id='7103'><display-name>Первый канал</display-name>"
    "<icon src='//i.example/7103.png'/></channel>"
    "<programme start='20260109120000 +0300' channel='7103'><title>Новости</title></programme>"
    "<programme start='20260109130000 +0300' channel='other'><title>Чужое</title></programme>"
    "</tv>"
)
CP1251_BYTES = XML.encode("cp1251")


def test_decode_declared_cp1251() -> None:
    text = decode_xmltv(CP1251_BYTES)
    assert "Первый канал" in text


def test_decode_cp1251_without_declaration() -> None:
    raw = XML.split("?>", 1)[1].encode("cp1251")  # нет объявления
    assert "Первый канал" in decode_xmltv(raw)


def test_decode_utf8_passthrough() -> None:
    raw = XML.replace("encoding='windows-1251'", "encoding='utf-8'").encode("utf-8")
    assert "Первый канал" in decode_xmltv(raw)


def test_parse_channels_from_bytes() -> None:
    channels = parse_xmltv_channels(CP1251_BYTES)
    assert len(channels) == 1
    assert channels[0].id == "7103"
    assert channels[0].display_names == ["Первый канал"]
    assert channels[0].icon_url == "//i.example/7103.png"


def test_parse_programmes_filtered_by_channel_ids() -> None:
    programmes = parse_xmltv_programmes(CP1251_BYTES, {"7103"})
    assert [p.title for p in programmes] == ["Новости"]
    assert programmes[0].channel == "7103"


def test_parse_gzip_source_bytes() -> None:
    payload = gzip.compress(CP1251_BYTES)
    # enrich распаковывает gzip до вызова парсера — проверяем совместимость
    channels = parse_xmltv_channels(gzip.decompress(payload))
    assert channels[0].id == "7103"


def test_namespace_epg_prefixes_ids() -> None:
    channels = parse_xmltv_channels(CP1251_BYTES)
    programmes = parse_xmltv_programmes(CP1251_BYTES, {"7103"})
    ns_channels, ns_programmes = namespace_epg("epg-pw-ru", channels, programmes)
    assert ns_channels[0].id == "epg-pw-ru:7103"
    assert ns_programmes[0].channel == "epg-pw-ru:7103"


def test_same_raw_id_across_sources_does_not_collide() -> None:
    """Числовой id «7103» в двух источниках — разные каналы после неймспейса."""
    ch_a = parse_xmltv_channels(CP1251_BYTES)
    ns_a, _ = namespace_epg("epg-pw-ru", ch_a, [])
    xml_b = XML.replace("Первый канал", "Другой канал")
    ch_b = parse_xmltv_channels(xml_b.encode("utf-8"))
    ns_b, _ = namespace_epg("iptvx-ru", ch_b, [])
    catalog = [Channel(channel_id="ru-x", name="Первый канал", country="RU")]
    matches = match_epg(catalog, [*ns_a, *ns_b], AliasIndex([]))
    assert len(matches) == 1
    assert matches[0].tvg_id == "epg-pw-ru:7103"
    assert matches[0].method == MatchMethod.NORMALIZED_NAME
