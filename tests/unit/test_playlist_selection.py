"""Тесты отбора плейлиста: один поток на канал (#6) и tvg-chno (#7)."""

from __future__ import annotations

from iptv_monitor.domain.channel import Channel
from iptv_monitor.domain.enums import QualityLevel, StreamProtocol
from iptv_monitor.domain.stream import Stream
from iptv_monitor.filtering import best_per_channel
from iptv_monitor.filtering.country_profiles import SelectedStream
from iptv_monitor.generators import M3UEntry, assign_channel_numbers, render_m3u
from iptv_monitor.scoring import StreamScore


def _sel(channel_id: str, name: str, stream_id: str, url: str, score: float) -> SelectedStream:
    return SelectedStream(
        channel=Channel(channel_id=channel_id, name=name, country="RU"),
        stream=Stream(
            stream_id=stream_id,
            channel_id=channel_id,
            url=url,
            protocol=StreamProtocol.HLS,
            source_id="s",
        ),
        score=StreamScore(stream_id=stream_id, checks=6, score=score, level=QualityLevel.GOOD),
        included=True,
    )


def test_best_stream_wins_per_channel() -> None:
    group = [
        _sel("ru-a", "Канал A", "s1", "http://x/1.m3u8", 80.0),
        _sel("ru-a", "Канал A", "s2", "http://x/2.m3u8", 90.0),
        _sel("ru-a", "Канал A", "s3", "http://x/3.m3u8", 90.0),
        _sel("ru-b", "Канал B", "s4", "http://x/4.m3u8", 85.0),
    ]
    best = best_per_channel(group)
    assert len(best) == 2
    # Канал A: лучший по score; тай-брейк 90.0 — больше проверок нет, короче URL
    winner = next(s for s in best if s.channel.channel_id == "ru-a")
    assert winner.stream.stream_id == "s2"
    # Проигравшие исключены с объяснением в отчёте
    losers = [s for s in group if not s.included]
    assert {s.stream.stream_id for s in losers} == {"s1", "s3"}
    assert all("superseded" in r for s in losers for r in s.reasons)


def test_order_of_other_channels_preserved() -> None:
    group = [
        _sel("ru-a", "Канал A", "s1", "http://x/a", 80.0),
        _sel("ru-b", "Канал B", "s2", "http://x/b", 85.0),
        _sel("ru-c", "Канал C", "s3", "http://x/c", 70.0),
        _sel("ru-b", "Канал B", "s4", "http://x/b2", 95.0),
    ]
    best = best_per_channel(group)
    assert [s.channel.channel_id for s in best] == ["ru-a", "ru-b", "ru-c"]


def test_singletons_untouched() -> None:
    group = [_sel("ru-a", "Канал A", "s1", "http://x/a", 80.0)]
    best = best_per_channel(group)
    assert len(best) == 1 and best[0].included and not best[0].reasons


def _entries(*ids: str) -> list[M3UEntry]:
    return [
        M3UEntry(name=f"Канал {i}", url=f"http://x/{i}", tvg_id=i, group_title="general")
        for i in ids
    ]


def test_channel_numbers_deterministic() -> None:
    a = _entries("1tv.ru@SD", "russia1.ru@SD", "ntv.ru@SD")
    b = _entries("1tv.ru@SD", "russia1.ru@SD", "ntv.ru@SD")
    assign_channel_numbers(a)
    assign_channel_numbers(b)
    assert [e.tvg_chno for e in a] == [e.tvg_chno for e in b]
    assert all(e.tvg_chno is not None for e in a)
    assert len({e.tvg_chno for e in a}) == len(a)  # уникальны


def test_channel_numbers_stable_when_unrelated_channel_removed() -> None:
    full = _entries("a.ru@SD", "b.ru@SD", "c.ru@SD")
    assign_channel_numbers(full)
    subset = _entries("a.ru@SD", "c.ru@SD")
    assign_channel_numbers(subset)
    by_id = {e.tvg_id: e.tvg_chno for e in subset}
    for e in full:
        if e.tvg_id in by_id:
            assert by_id[e.tvg_id] == e.tvg_chno, f"номер {e.tvg_id} прыгнул"


def test_channel_numbers_overrides_reserved() -> None:
    entries = _entries("first.ru@SD", "second.ru@SD")
    entries[0].name = "Первый канал (1080p)"
    assign_channel_numbers(entries, overrides={"Первый канал": 1})
    assert entries[0].tvg_chno == 1
    # override-номер не выдаётся никому другому
    assert entries[1].tvg_chno != 1


def test_render_m3u_includes_chno() -> None:
    entries = _entries("1tv.ru@SD")
    assign_channel_numbers(entries, overrides={"Канал 1": 5})
    text = render_m3u(entries)
    assert f'tvg-chno="{entries[0].tvg_chno}"' in text
    bare = render_m3u([M3UEntry(name="X", url="http://x")])
    assert "tvg-chno" not in bare
