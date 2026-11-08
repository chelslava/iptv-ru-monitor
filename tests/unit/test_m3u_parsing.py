"""Тесты разбора M3U-плейлистов."""

from __future__ import annotations

from iptv_monitor.discovery.base import parse_m3u

SAMPLE = """\
#EXTM3U
#EXTINF:-1 tvg-id="1tv.ru" tvg-name="Первый" tvg-logo="https://l/1.png" group-title="Общие",Первый
https://stream.example.org/1tv.m3u8
#EXTVLCOPT:http-user-agent=VLC
#EXTINF:-1 group-title="Спорт",Матч ТВ HD
https://stream.example.org/match.m3u8
https://orphan.example.org/without-extinf.m3u8
#EXTINF:-1,Без атрибутов
https://stream.example.org/plain.ts
"""


def test_parses_attributes_and_urls() -> None:
    entries = parse_m3u(SAMPLE, "test-source")
    assert len(entries) == 3

    first = entries[0]
    assert first.source_id == "test-source"
    assert first.name == "Первый"
    assert first.tvg_id == "1tv.ru"
    assert first.tvg_name == "Первый"
    assert first.tvg_logo == "https://l/1.png"
    assert first.group_title == "Общие"
    assert first.url == "https://stream.example.org/1tv.m3u8"

    second = entries[1]
    assert second.name == "Матч ТВ HD"
    assert second.tvg_id is None

    third = entries[2]
    assert third.name == "Без атрибутов"
    assert third.url.endswith("plain.ts")


def test_orphan_url_without_extinf_is_skipped() -> None:
    entries = parse_m3u(SAMPLE, "test-source")
    urls = [e.url for e in entries]
    assert "https://orphan.example.org/without-extinf.m3u8" not in urls


def test_empty_playlist() -> None:
    assert parse_m3u("#EXTM3U\n", "src") == []
    assert parse_m3u("", "src") == []
