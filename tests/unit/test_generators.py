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


def test_index_html_includes_catalog_search() -> None:
    """Статус-страница содержит поиск по каталогу (волна 3)."""
    from iptv_monitor.generators.report import render_index_html

    page = render_index_html(
        site_title="iptv-ru-monitor — RU",
        playlists=[
            {"title": "Основной", "filename": "russia.m3u", "url": "ru/russia.m3u", "included": 5}
        ],
        report_path="ru/report.json",
        last_generated="2026-11-10 08:00",
        catalog_path="ru/channels.json",
    )
    assert 'id="catalog-search"' in page
    assert "channels.json" in page
    assert "report.json" in page
    # без catalog_path секции нет (старое поведение)
    page_min = render_index_html(
        site_title="x",
        playlists=[],
        report_path="ru/report.json",
        last_generated="2026-11-10 08:00",
    )
    assert 'id="catalog-search"' not in page_min


def test_index_html_includes_player_layer() -> None:
    """Каталог содержит плеер-слой: модалка, streams.json, кнопка ▶ (плеер MVP)."""
    from iptv_monitor.generators.report import render_index_html

    page = render_index_html(
        site_title="iptv-ru-monitor — RU",
        playlists=[
            {"title": "Основной", "filename": "russia.m3u", "url": "ru/russia.m3u", "included": 5}
        ],
        report_path="ru/report.json",
        last_generated="2026-11-10 08:00",
        catalog_path="ru/channels.json",
    )
    # модалка плеера и его скрипт
    assert 'id="iptv-player"' in page
    assert 'id="iptv-player-video"' in page
    assert "../assets/player.js" in page
    # третий источник данных — streams.json (URL только включённых потоков)
    assert 'fetch("ru/streams.json")' in page
    # ссылка плейлиста в модалке — относительное имя файла
    assert 'href="russia.m3u">Плейлист (M3U)</a>' in page
    # кандидаты: только включённые HLS-потоки, сортировка по score/uptime
    assert 'protocol !== "hls"' in page
    assert ".play-btn" in page
    # без catalog_path плеера тоже нет
    page_min = render_index_html(
        site_title="x",
        playlists=[],
        report_path="ru/report.json",
        last_generated="2026-11-10 08:00",
    )
    assert 'id="iptv-player"' not in page_min
    assert "../assets/player.js" not in page_min


def test_static_assets_vendored() -> None:
    """Вендоренные статики плеера существуют и не пусты (см. static/README.md)."""
    from pathlib import Path

    static_dir = (
        Path(__file__).resolve().parents[2] / "src" / "iptv_monitor" / "generators" / "static"
    )
    hls = static_dir / "hls.light.min.js"
    player = static_dir / "player.js"
    assert hls.is_file() and hls.stat().st_size > 100_000  # лёгкая сборка hls.js
    assert player.is_file() and player.stat().st_size > 1_000
    player_src = player.read_text(encoding="utf-8")
    assert "window.IptvPlayer" in player_src  # публичное API для страницы
    assert "recoverMediaError" in player_src  # failover MEDIA-ошибок
    assert "data-channel" not in player_src  # клики ▶ живут на странице, не в плеере
