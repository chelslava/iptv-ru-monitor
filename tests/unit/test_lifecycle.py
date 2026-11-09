"""Тесты автодеградации мёртвых потоков (issue #8)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from iptv_monitor.domain.channel import Channel
from iptv_monitor.domain.check_result import CheckResult
from iptv_monitor.domain.enums import CheckErrorCode, PublicPolicy, StreamProtocol
from iptv_monitor.domain.source import SourceConfig
from iptv_monitor.domain.stream import Stream
from iptv_monitor.filtering import decide_publication
from iptv_monitor.history.lifecycle import analyze_lifecycle

_BASE = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def _res(stream_id: str, minutes_ago: int, *, ok: bool) -> CheckResult:
    return CheckResult(
        stream_id=stream_id,
        checked_at=_BASE - timedelta(minutes=minutes_ago),
        probe_location="github-runner",
        error_code=None if ok else CheckErrorCode.TIMEOUT,
    )


def test_consecutive_failures_counted_from_latest() -> None:
    # 3 свежих провала, затем успехи — счётчик 3
    results = [
        _res("s", 60, ok=True),
        _res("s", 50, ok=True),
        _res("s", 40, ok=False),
        _res("s", 30, ok=False),
        _res("s", 20, ok=False),
    ]
    lc = analyze_lifecycle(results, stale_after=6, deny_after=12)
    assert lc.consecutive_failures == 3
    assert not lc.stale and not lc.denied


def test_single_success_resets_counter() -> None:
    results = [
        _res("s", 40, ok=False),
        _res("s", 30, ok=False),
        _res("s", 20, ok=False),
        _res("s", 10, ok=False),
        _res("s", 5, ok=True),  # самый свежий — успех
    ]
    lc = analyze_lifecycle(results, stale_after=2, deny_after=4)
    assert lc.consecutive_failures == 0
    assert not lc.stale and not lc.denied


def test_stale_and_denied_thresholds() -> None:
    results = [_res("s", 60 - i, ok=False) for i in range(8)]
    lc = analyze_lifecycle(results, stale_after=6, deny_after=12)
    assert lc.stale and not lc.denied
    results += [_res("s", 61 + i, ok=False) for i in range(4)]  # ещё провалы позже по времени
    lc12 = analyze_lifecycle(results, stale_after=6, deny_after=12)
    assert lc12.consecutive_failures == 12
    assert lc12.denied and lc12.stale


def test_results_order_does_not_matter() -> None:
    ordered = [_res("s", 30, ok=False), _res("s", 20, ok=False), _res("s", 10, ok=False)]
    shuffled = [ordered[2], ordered[0], ordered[1]]
    a = analyze_lifecycle(ordered, stale_after=6, deny_after=12)
    b = analyze_lifecycle(shuffled, stale_after=6, deny_after=12)
    assert a.consecutive_failures == b.consecutive_failures == 3


def _stream() -> Stream:
    return Stream(
        stream_id="s1",
        channel_id="c1",
        url="https://stream.example/live.m3u8",
        protocol=StreamProtocol.HLS,
        source_id="src",
    )


def test_auto_denied_blocks_publication() -> None:
    channel = Channel(channel_id="c1", name="Канал", country="RU", is_public=True)
    source = SourceConfig(id="src", adapter="iptv_org", public_policy=PublicPolicy.ALLOW)
    decision = decide_publication(channel, _stream(), source, denied_consecutive_failures=12)
    assert not decision.allowed
    assert any("auto-denied (12 consecutive failures)" in r for r in decision.reasons)


def test_stale_does_not_block_publication() -> None:
    """stale (меньше порога deny) не передаётся в решение — поток публикуется."""
    channel = Channel(channel_id="c1", name="Канал", country="RU", is_public=True)
    source = SourceConfig(id="src", adapter="iptv_org", public_policy=PublicPolicy.ALLOW)
    decision = decide_publication(channel, _stream(), source, denied_consecutive_failures=None)
    assert decision.allowed
    assert decision.reasons == []
