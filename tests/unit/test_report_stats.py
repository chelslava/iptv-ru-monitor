"""Тесты отчёта и статистики: uptime 7д/30д, stats.json (issue #9)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from iptv_monitor.domain.channel import Channel
from iptv_monitor.domain.check_result import CheckResult
from iptv_monitor.domain.enums import QualityLevel, StreamProtocol
from iptv_monitor.domain.stream import Stream
from iptv_monitor.filtering import SelectedStream
from iptv_monitor.generators import build_report, build_stats, render_index_html
from iptv_monitor.scoring import StreamScore

_NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def _res(stream_id: str, days_ago: float, *, ok: bool) -> CheckResult:
    return CheckResult(
        stream_id=stream_id,
        checked_at=_NOW - timedelta(days=days_ago),
        probe_location="github-runner",
        error_code=None if ok else CheckErrorCode.TIMEOUT,
    )


def _sel(stream_id: str, channel_id: str = "c1", score: float = 85.0) -> SelectedStream:
    return SelectedStream(
        channel=Channel(channel_id=channel_id, name="Канал", country="RU"),
        stream=Stream(
            stream_id=stream_id,
            channel_id=channel_id,
            url="https://x/live.m3u8",
            protocol=StreamProtocol.HLS,
            source_id="s",
        ),
        score=StreamScore(stream_id=stream_id, checks=6, score=score, level=QualityLevel.GOOD),
        included=True,
    )


from iptv_monitor.domain.enums import CheckErrorCode  # noqa: E402


def test_uptime_windows() -> None:
    # s1: 7д — 3/4 успеха (75%), в 30д попадает ещё 4 старых неудачи (3/8 = 37.5%)
    results = [
        _res("s1", 1, ok=True),
        _res("s1", 3, ok=True),
        _res("s1", 6, ok=False),
        _res("s1", 2, ok=True),
        _res("s1", 20, ok=False),
        _res("s1", 25, ok=False),
        _res("s1", 28, ok=False),
        _res("s1", 29, ok=False),
    ]
    report = build_report(
        country="RU",
        profile_id="ru_default",
        selections=[_sel("s1")],
        results=results,
        generated_at=_NOW,
    )
    entry = report["streams"][0]
    assert entry["uptime_7d_percent"] == 75.0
    assert entry["uptime_30d_percent"] == 37.5


def test_uptime_none_without_history() -> None:
    report = build_report(
        country="RU",
        profile_id="ru_default",
        selections=[_sel("unknown")],
        results=[_res("s1", 1, ok=True)],
        generated_at=_NOW,
    )
    entry = report["streams"][0]
    assert entry["uptime_7d_percent"] is None


def test_build_stats_counters_and_probes() -> None:
    results = [
        _res("s1", 0.1, ok=True),
        _res("s2", 2, ok=False),
        CheckResult(
            stream_id="s2",
            checked_at=_NOW - timedelta(days=1),
            probe_location="home-ru",
            error_code=None,
        ),
    ]
    stats = build_stats(
        country="RU",
        channels_total=500,
        selections=[_sel("s1"), _sel("s2", channel_id="c2")],
        results=results,
        generated_at=_NOW,
        epg_playlist_channels=1,
    )
    assert stats["catalog"] == {"channels": 500, "streams": 2}
    assert stats["playlist"] == {"channels": 2, "streams": 2}
    assert stats["epg"] == {"playlist_channels": 1, "playlist_total": 2}
    assert stats["probes_last_check"]["github-runner"].startswith("2026-11-09")
    assert stats["probes_last_check"]["home-ru"].startswith("2026-11-08")
    assert stats["top_error_codes"].get("timeout") == 1


def test_index_html_renders_counters_and_top() -> None:
    stats = {
        "catalog": {"channels": 500, "streams": 900},
        "playlist": {"channels": 59, "streams": 59},
        "epg": {"playlist_channels": 40, "playlist_total": 59},
        "lifecycle": {"stale": 3, "denied": 7},
        "probes_last_check": {"github-runner": "2026-11-09T06:00:00+00:00"},
    }
    top = [
        {"name": "Первый канал", "logo": None, "group": "general", "score": 90.0, "uptime": 98.5}
    ]
    page = render_index_html(
        site_title="test",
        playlists=[{"title": "Россия", "url": "ru/russia.m3u", "included": 59}],
        report_path="ru/report.json",
        last_generated="2026-11-09 12:00",
        stats=stats,
        top_channels=top,
    )
    assert "59" in page and "каналов в плейлисте" in page
    assert "40/59" in page
    assert "Первый канал" in page and "98.5" in page
    assert "stats.json" in page
    # экранирование: URL логотипа с кавычкой не ломает разметку
    evil = [{"name": "X", "logo": '"><script>', "group": "g", "score": 1, "uptime": 1}]
    page_evil = render_index_html(
        site_title="t",
        playlists=[],
        report_path="ru/report.json",
        last_generated="",
        stats=stats,
        top_channels=evil,
    )
    assert "<script>" not in page_evil
