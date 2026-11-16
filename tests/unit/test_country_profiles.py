"""Тесты страновых профилей отбора: порог score и exclude_categories."""

from __future__ import annotations

from iptv_monitor.domain.channel import Channel
from iptv_monitor.domain.enums import Category, QualityLevel, StreamProtocol
from iptv_monitor.domain.stream import Stream
from iptv_monitor.filtering.country_profiles import select_streams
from iptv_monitor.scoring import StreamScore
from iptv_monitor.settings import QualityProfileSettings


def _stream(stream_id: str, url: str) -> Stream:
    return Stream(
        stream_id=stream_id,
        channel_id=f"ch-{stream_id}",
        url=url,
        protocol=StreamProtocol.HLS,
        source_id="s",
    )


def _channel(channel_id: str, category: Category) -> Channel:
    return Channel(
        channel_id=channel_id, name=f"Канал {channel_id}", country="RU", category=category
    )


def _score(stream_id: str, score: float) -> StreamScore:
    return StreamScore(stream_id=stream_id, checks=6, score=score, level=QualityLevel.GOOD)


def _profile(**overrides: object) -> QualityProfileSettings:
    body: dict[str, object] = {"country": "RU", "min_score": 50, "min_checks": 5}
    body.update(overrides)
    return QualityProfileSettings.model_validate(body)


def test_stream_below_min_score_excluded() -> None:
    streams = [_stream("s1", "http://x/1")]
    channels = [_channel("ch-s1", Category.GENERAL)]
    scores = {"s1": _score("s1", 40.0)}
    result = select_streams(
        profile=_profile(), channels=channels, streams=streams, scores=scores, decisions={}
    )
    assert len(result) == 1
    assert not result[0].included
    assert any("below profile minimum" in r for r in result[0].reasons)


def test_stream_passing_threshold_included() -> None:
    streams = [_stream("s1", "http://x/1")]
    channels = [_channel("ch-s1", Category.GENERAL)]
    scores = {"s1": _score("s1", 85.0)}
    result = select_streams(
        profile=_profile(), channels=channels, streams=streams, scores=scores, decisions={}
    )
    assert result[0].included and not result[0].reasons


def test_exclude_categories_drops_adult() -> None:
    """Канал 18+ исключается из профиля даже при отличном score (GoodTV)."""
    streams = [_stream("s1", "http://x/1"), _stream("s2", "http://x/2")]
    channels = [
        _channel("ch-s1", Category.ADULT),
        _channel("ch-s2", Category.GENERAL),
    ]
    scores = {"s1": _score("s1", 95.0), "s2": _score("s2", 85.0)}
    result = select_streams(
        profile=_profile(exclude_categories=[Category.ADULT]),
        channels=channels,
        streams=streams,
        scores=scores,
        decisions={},
    )
    by_id = {sel.stream.stream_id: sel for sel in result}
    assert not by_id["s1"].included
    assert any("excluded by profile" in r for r in by_id["s1"].reasons)
    assert by_id["s2"].included and not by_id["s2"].reasons


def test_exclude_without_adult_keeps_stream() -> None:
    streams = [_stream("s1", "http://x/1")]
    channels = [_channel("ch-s1", Category.ADULT)]
    scores = {"s1": _score("s1", 85.0)}
    result = select_streams(
        profile=_profile(), channels=channels, streams=streams, scores=scores, decisions={}
    )
    assert result[0].included


def test_include_categories_still_wins_for_kids_sport() -> None:
    streams = [_stream("s1", "http://x/1")]
    channels = [_channel("ch-s1", Category.ADULT)]
    scores = {"s1": _score("s1", 85.0)}
    result = select_streams(
        profile=_profile(categories=[Category.KIDS]),
        channels=channels,
        streams=streams,
        scores=scores,
        decisions={},
    )
    assert not result[0].included
    assert any("not in profile" in r for r in result[0].reasons)
