"""Тесты enrichment: gzip-XMLTV, нормализация URL логотипов, алиасы."""

from __future__ import annotations

import gzip

import pytest

from iptv_monitor.discovery import DiscoveredStream
from iptv_monitor.domain.source import SourceConfig
from iptv_monitor.metadata import AliasIndex, match_epg, parse_xmltv
from iptv_monitor.metadata.epg.parser import EpgChannelData
from iptv_monitor.normalization import normalize_discovered
from iptv_monitor.settings import AliasRule, CategoriesFile

XMLTV = """<?xml version="1.0" encoding="UTF-8"?>
<tv>
  <channel id="5735"><display-name>Первый канал</display-name></channel>
  <channel id="5812"><display-name>Матч ТВ</display-name></channel>
  <programme start="20260108120000 +0300" channel="5735"><title>Новости</title></programme>
</tv>
"""


def _channels_and_streams():
    from iptv_monitor.domain.channel import Channel

    return [
        Channel(channel_id="ru-pervyj-kanal", name="Первый канал", country="RU", tvg_id="1tv.ru"),
        Channel(channel_id="ru-match", name="Матч", country="RU"),
    ]


def test_parse_xmltv_gzip_content() -> None:
    """gzip-файл .xml.gz распаковывается перед разбором (как в enrich)."""
    payload = gzip.decompress(gzip.compress(XMLTV.encode("utf-8")))
    channels, programmes = parse_xmltv(payload.decode("utf-8"))
    assert {c.id for c in channels} == {"5735", "5812"}
    assert len(programmes) == 1


def test_parse_xmltv_icon() -> None:
    """Иконка канала из <icon src=...> разбирается (источник логотипов)."""
    xmltv = (
        '<?xml version="1.0"?><tv>'
        '<channel id="5735"><display-name>Первый</display-name>'
        '<icon src="//epg.pw/i/5735.png"/></channel>'
        "</tv>"
    )
    channels, _ = parse_xmltv(xmltv)
    assert channels[0].icon_url == "//epg.pw/i/5735.png"


def test_alias_applied_only_when_tvg_id_in_epg() -> None:
    """Алиас с tvg_id, отсутствующим в EPG, пропускается — работает имя."""
    channels = _channels_and_streams()
    epg = [EpgChannelData(id="5735", display_names=["Первый канал"])]
    # алиас ведёт на id формата iptv-org, которого нет в этом EPG
    aliases = AliasIndex([AliasRule(name="Первый канал", tvg_id="1tv.ru", manual=True)])

    matches = match_epg(channels, epg, aliases)
    first = next(m for m in matches if m.channel_id == "ru-pervyj-kanal")
    assert first.method.value == "normalized_name"
    assert first.tvg_id == "5735"  # а не 1tv.ru из алиаса


def test_alias_wins_when_tvg_id_present() -> None:
    channels = _channels_and_streams()
    epg = [EpgChannelData(id="1tv.ru", display_names=["Совсем другое имя"])]
    # канал «Матч» без tvg_id: точного совпадения нет, имя не совпадает —
    # срабатывает только алиас, чей id присутствует в EPG.
    aliases = AliasIndex([AliasRule(name="Матч", tvg_id="1tv.ru", manual=True)])

    matches = match_epg(channels, epg, aliases)
    match = next(m for m in matches if m.channel_id == "ru-match")
    assert match.method.value == "alias"
    assert match.tvg_id == "1tv.ru"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("//i.imgur.com/abc.png", "https://i.imgur.com/abc.png"),
        ("https://i.imgur.com/ok.png", "https://i.imgur.com/ok.png"),
        ("http://example.org/x.png", "http://example.org/x.png"),
        ("javascript:alert(1)", None),
        ("data:image/png;base64,xxx", None),
        (None, None),
    ],
)
def test_logo_url_normalization(raw: str | None, expected: str | None) -> None:
    source = SourceConfig(id="src", adapter="remote_m3u", country="RU")
    entry = DiscoveredStream(
        source_id="src", name="Канал", url="https://s.example/a.m3u8", tvg_logo=raw
    )
    channels, _ = normalize_discovered([entry], [source], CategoriesFile(rules=[]))
    assert channels[0].logo_url == expected
