"""Тесты генерации M3U и XMLTV."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from iptv_monitor.domain.channel import Channel
from iptv_monitor.domain.enums import Category
from iptv_monitor.domain.stream import Stream
from iptv_monitor.generators.m3u import entry_for, render_m3u
from iptv_monitor.generators.xmltv import render_xmltv
from iptv_monitor.metadata.epg.parser import EpgProgramme, parse_xmltv


def _channel() -> Channel:
    return Channel(
        channel_id="ru-pervyj-kanal",
        name="Первый канал",
        country="RU",
        category=Category.GENERAL,
        tvg_id="1tv.ru",
        logo_url="https://example.org/logo/1tv.png",
    )


def _stream() -> Stream:
    return Stream(
        stream_id="abc",
        channel_id="ru-pervyj-kanal",
        url="https://stream.example.org/1tv/index.m3u8",
        protocol="hls",
        source_id="src",
    )


def test_m3u_rendering_with_epg_url() -> None:
    entry = entry_for(_channel(), _stream())
    text = render_m3u([entry], epg_url="russia.xml")
    assert text.startswith('#EXTM3U url-tvg="russia.xml"')
    assert 'tvg-id="1tv.ru"' in text
    assert 'tvg-name="Первый канал"' in text
    assert 'tvg-logo="https://example.org/logo/1tv.png"' in text
    assert "group-title=" in text
    assert "https://stream.example.org/1tv/index.m3u8" in text


def test_m3u_escapes_quotes() -> None:
    channel = _channel().model_copy(update={"name": 'Канал "Экран"'})
    text = render_m3u([entry_for(channel, _stream())])
    assert 'Канал "Экран"' not in text
    assert "Канал 'Экран'" in text


def _programme() -> EpgProgramme:
    start = datetime(2026, 1, 8, 12, 0, 0, tzinfo=UTC)
    return EpgProgramme(
        channel="1tv.ru",
        start=start,
        stop=start + timedelta(hours=1),
        title="Новости",
        description="Выпуск",
    )


def test_xmltv_roundtrip() -> None:
    channels = [_channel(), _channel().model_copy(update={"tvg_id": None})]
    other = _programme().model_copy(update={"channel": "other"})
    text = render_xmltv(channels, [_programme(), other])
    assert text.startswith("<?xml")  # XML-декларация обязательна (issue #26)

    epg_channels, programmes = parse_xmltv(text)
    assert {c.id for c in epg_channels} == {"1tv.ru"}
    assert len(programmes) == 1  # программа «other» отфильтрована
    assert programmes[0].title == "Новости"
    assert programmes[0].stop is not None


def test_channels_without_tvg_id_excluded_from_xmltv() -> None:
    text = render_xmltv([_channel().model_copy(update={"tvg_id": None})], [_programme()])
    epg_channels, programmes = parse_xmltv(text)
    assert epg_channels == []
    assert programmes == []
