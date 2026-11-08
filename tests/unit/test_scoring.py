"""Тесты скоринга потоков."""

from __future__ import annotations

from iptv_monitor.domain.enums import QualityLevel
from iptv_monitor.scoring import score_stream
from iptv_monitor.settings import QualityLevels, QualityWeights

WEIGHTS = QualityWeights()
LEVELS = QualityLevels()


def test_short_history_is_insufficient(make_result) -> None:
    results = [make_result() for _ in range(3)]
    score = score_stream("s1", results, weights=WEIGHTS, levels=LEVELS, min_checks=5)
    assert score.level == QualityLevel.INSUFFICIENT_DATA
    assert score.score is None


def test_perfect_history_is_excellent(make_result) -> None:
    results = [make_result() for _ in range(10)]
    score = score_stream("s1", results, weights=WEIGHTS, levels=LEVELS, min_checks=5)
    assert score.score is not None and score.score >= 90
    assert score.level == QualityLevel.EXCELLENT


def test_all_failures_is_failed(make_result) -> None:
    results = [
        make_result(
            error_code="http_5xx",
            error_message="boom",
            playlist_ok=None,
            first_segment_ok=None,
        )
        for _ in range(10)
    ]
    score = score_stream("s1", results, weights=WEIGHTS, levels=LEVELS, min_checks=5)
    assert score.score == 0
    assert score.level == QualityLevel.FAILED


def test_flaky_history_is_between(make_result) -> None:
    results = [make_result() for _ in range(6)] + [
        make_result(error_code="timeout", error_message="", playlist_ok=None, first_segment_ok=None)
        for _ in range(4)
    ]
    score = score_stream("s1", results, weights=WEIGHTS, levels=LEVELS, min_checks=5)
    assert score.score is not None
    assert 50 <= score.score < 90
    assert score.level in (QualityLevel.GOOD, QualityLevel.UNSTABLE)


def test_missing_components_score_zero_contribution(make_result) -> None:
    # Только HTTP-успехи: HLS/медиа-компоненты отсутствуют и не завышают балл.
    results = [
        make_result(
            playlist_ok=None,
            first_segment_ok=None,
            width=None,
            height=None,
            startup_time_ms=None,
        )
        for _ in range(10)
    ]
    score = score_stream("s1", results, weights=WEIGHTS, levels=LEVELS, min_checks=5)
    assert score.score is not None
    # только availability (35) + частично hls=0/stability=0 → существенно ниже отличного
    assert score.score <= 35
    assert score.level == QualityLevel.FAILED


def test_weights_sum_to_one() -> None:
    total = sum(WEIGHTS.model_dump().values())
    assert abs(total - 1.0) < 1e-9
