"""Тесты поиска кандидатов на подтверждение публикации."""

from __future__ import annotations

from iptv_monitor.domain.channel import Channel
from iptv_monitor.domain.enums import QualityLevel
from iptv_monitor.domain.stream import Stream, make_stream_id
from iptv_monitor.filtering import decide_publication, find_candidates
from iptv_monitor.filtering.candidates import ApprovalCandidate
from iptv_monitor.scoring.quality import StreamScore, score_stream
from iptv_monitor.settings import ApprovalSettings, QualityLevels, QualityWeights

WEIGHTS = QualityWeights()
LEVELS = QualityLevels()
APPROVAL = ApprovalSettings(min_score=75, min_checks=6, min_probe_locations=2)


def _channel(channel_id: str = "ru-test") -> Channel:
    return Channel(channel_id=channel_id, name="Тестовый канал", country="RU", is_public=False)


def _stream(url: str, channel_id: str = "ru-test") -> Stream:
    return Stream(
        stream_id=make_stream_id(url),
        channel_id=channel_id,
        url=url,
        protocol="hls",
        source_id="src-review",
    )


def _score(stream_id: str, results) -> StreamScore:
    return score_stream(stream_id, results, weights=WEIGHTS, levels=LEVELS, min_checks=6)


def _history_for(stream: Stream, locations: list[str], *, segment: bool = True):
    """История успешных проверок из перечисленных точек наблюдения."""
    from iptv_monitor.domain.check_result import CheckResult

    results = []
    for location in locations:
        for _ in range(3):
            results.append(
                CheckResult(
                    stream_id=stream.stream_id,
                    probe_location=location,
                    http_status=200,
                    playlist_ok=True,
                    first_segment_ok=segment,
                    startup_time_ms=1500,
                    width=1920,
                    height=1080,
                )
            )
    return results


def _build(streams, histories, *, approved=None):
    channel = _channel()
    decisions = {
        s.stream_id: decide_publication(channel, s, _review_source(), approved or set())
        for s in streams
    }
    scores = {s.stream_id: _score(s.stream_id, histories[s.stream_id]) for s in streams}
    history = {s.stream_id: histories[s.stream_id] for s in streams}
    return channel, decisions, scores, history


def _review_source():
    from iptv_monitor.domain.source import SourceConfig

    return SourceConfig(id="src-review", adapter="custom_m3u", public_policy="review", country="RU")


def test_qualified_stream_is_candidate() -> None:
    stream = _stream("https://ok.example/a.m3u8")
    histories = {stream.stream_id: _history_for(stream, ["github-runner", "home-ru"])}
    channel, decisions, scores, history = _build([stream], histories)

    candidates = find_candidates(
        approval=APPROVAL,
        channels=[channel],
        streams=[stream],
        scores=scores,
        decisions=decisions,
        history=history,
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.stream_id == stream.stream_id
    assert candidate.channel_name == "Тестовый канал"
    assert candidate.probe_locations == ["github-runner", "home-ru"]
    assert candidate.segment_ok is True
    assert candidate.score >= 75


def test_single_probe_location_not_enough() -> None:
    stream = _stream("https://one.example/a.m3u8")
    histories = {stream.stream_id: _history_for(stream, ["github-runner"])}
    channel, decisions, scores, history = _build([stream], histories)

    candidates = find_candidates(
        approval=APPROVAL,
        channels=[channel],
        streams=[stream],
        scores=scores,
        decisions=decisions,
        history=history,
    )
    assert candidates == []


def test_missing_segment_not_enough() -> None:
    stream = _stream("https://noseg.example/a.m3u8")
    histories = {
        stream.stream_id: _history_for(stream, ["github-runner", "home-ru"], segment=False)
    }
    channel, decisions, scores, history = _build([stream], histories)

    candidates = find_candidates(
        approval=APPROVAL,
        channels=[channel],
        streams=[stream],
        scores=scores,
        decisions=decisions,
        history=history,
    )
    assert candidates == []


def test_already_approved_not_candidate() -> None:
    stream = _stream("https://approved.example/a.m3u8")
    histories = {stream.stream_id: _history_for(stream, ["github-runner", "home-ru"])}
    channel, decisions, scores, history = _build([stream], histories, approved={stream.stream_id})

    candidates = find_candidates(
        approval=APPROVAL,
        channels=[channel],
        streams=[stream],
        scores=scores,
        decisions=decisions,
        history=history,
    )
    assert candidates == []  # решение уже allowed — не кандидат


def test_secret_url_stream_not_candidate() -> None:
    stream = _stream("https://secret.example/a.m3u8?token=verysecretvalue123")
    histories = {stream.stream_id: _history_for(stream, ["github-runner", "home-ru"])}
    channel, decisions, scores, history = _build([stream], histories)

    candidates = find_candidates(
        approval=APPROVAL,
        channels=[channel],
        streams=[stream],
        scores=scores,
        decisions=decisions,
        history=history,
    )
    assert candidates == []  # секретный URL блокирует публикацию навсегда


def test_max_per_run_cap_keeps_best() -> None:
    streams = [_stream(f"https://cap.example/{i}.m3u8") for i in range(4)]
    histories = {s.stream_id: _history_for(s, ["github-runner", "home-ru"]) for s in streams}
    channel, decisions, scores, history = _build(streams, histories)
    approval = ApprovalSettings(min_score=75, min_checks=6, min_probe_locations=2, max_per_run=2)

    candidates = find_candidates(
        approval=approval,
        channels=[channel],
        streams=streams,
        scores=scores,
        decisions=decisions,
        history=history,
    )
    assert len(candidates) == 2


def test_insufficient_history_not_candidate() -> None:
    stream = _stream("https://short.example/a.m3u8")
    histories = {stream.stream_id: _history_for(stream, ["github-runner", "home-ru"])[:4]}
    channel, decisions, scores, history = _build([stream], histories)

    # score.level == insufficient_data при < min_checks
    assert scores[stream.stream_id].level == QualityLevel.INSUFFICIENT_DATA
    candidates = find_candidates(
        approval=APPROVAL,
        channels=[channel],
        streams=[stream],
        scores=scores,
        decisions=decisions,
        history=history,
    )
    assert candidates == []


def test_candidates_to_dicts_roundtrip() -> None:
    candidate = ApprovalCandidate(
        stream_id="abc",
        channel_id="ru-x",
        channel_name="Канал",
        score=88.5,
        level="good",
        checks=8,
        probe_locations=["github-runner", "home-ru"],
        segment_ok=True,
    )
    from iptv_monitor.filtering import candidates_to_dicts

    data = candidates_to_dicts([candidate])
    assert data[0]["channel"] == "Канал"
    assert data[0]["score"] == 88.5
    assert data[0]["probe_locations"] == ["github-runner", "home-ru"]


# --- волна 3: приоритетная очередь approval -------------------------------


def _approval_stream(n: int) -> Stream:
    from iptv_monitor.domain.enums import StreamProtocol
    from iptv_monitor.domain.stream import Stream, make_stream_id

    url = f"https://ord{n}.example/live.m3u8"
    return Stream(
        stream_id=make_stream_id(url),
        channel_id=f"ru-ord{n}",
        url=url,
        protocol=StreamProtocol.HLS,
        source_id="test",
    )


def test_order_streams_approval_tiers() -> None:
    """Готовые к кандидату (сегмент есть, второй точки нет) идут первыми."""
    from iptv_monitor.filtering.candidates import order_streams_for_approval

    s_ready, s_plain, s_approved = (
        _approval_stream(0),
        _approval_stream(1),
        _approval_stream(2),
    )
    approved = {s_approved.stream_id}
    from iptv_monitor.domain.check_result import CheckResult

    history = {
        s_ready.stream_id: [
            CheckResult(
                stream_id=s_ready.stream_id,
                probe_location="github-runner",
                http_status=200,
                playlist_ok=True,
                first_segment_ok=True,
            )
        ],
        s_approved.stream_id: [
            CheckResult(
                stream_id=s_approved.stream_id,
                probe_location="github-runner",
                http_status=200,
                playlist_ok=True,
                first_segment_ok=True,
            )
        ],
    }
    ordered = order_streams_for_approval(
        [s_plain, s_approved, s_ready], history, approved, probe_location="home-ru"
    )
    assert ordered[0].stream_id == s_ready.stream_id  # готовый — первый
    # подтверждённый и без сегмента — в хвосте (каталожный порядок)
    assert {ordered[1].stream_id, ordered[2].stream_id} == {
        s_plain.stream_id,
        s_approved.stream_id,
    }


def test_order_streams_deterministic_by_successes() -> None:
    """Больше успешных проверок извне — выше; tie — по stream_id."""
    from iptv_monitor.domain.check_result import CheckResult
    from iptv_monitor.filtering.candidates import order_streams_for_approval

    a, b = _approval_stream(0), _approval_stream(1)

    def _ok(n: int) -> list[CheckResult]:
        return [
            CheckResult(
                stream_id=n,
                probe_location="github-runner",
                http_status=200,
                playlist_ok=True,
                first_segment_ok=True,
            )
        ]

    history = {
        a.stream_id: _ok(a.stream_id),
        b.stream_id: _ok(b.stream_id) * 2,
    }
    ordered = order_streams_for_approval([a, b], history, set(), probe_location="home-ru")
    # оба готовы; больше успешных проверок извне — выше
    assert [s.stream_id for s in ordered] == [b.stream_id, a.stream_id]
