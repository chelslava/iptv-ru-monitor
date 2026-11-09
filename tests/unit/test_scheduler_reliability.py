"""Надёжность run_checks: исключение в check_stream не теряет прогон (issue #19)."""

from __future__ import annotations

import pytest

from iptv_monitor.checking import scheduler
from iptv_monitor.checking.scheduler import run_checks
from iptv_monitor.domain.check_result import CheckResult
from iptv_monitor.domain.enums import CheckErrorCode, StreamProtocol
from iptv_monitor.domain.stream import Stream, make_stream_id
from iptv_monitor.settings import AppSettings


def _stream(n: int) -> Stream:
    url = f"https://n{n}.example/live.m3u8"
    return Stream(
        stream_id=make_stream_id(url),
        channel_id=f"ru-test-{n}",
        url=url,
        protocol=StreamProtocol.HLS,
        source_id="test",
    )


@pytest.mark.asyncio
async def test_exception_in_one_stream_keeps_batch(monkeypatch) -> None:
    """Один падающий поток -> CheckResult с unknown, остальные результаты живы."""
    streams = [_stream(0), _stream(1), _stream(2)]
    broken_id = streams[1].stream_id

    async def flaky(stream, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if stream.stream_id == broken_id:
            raise RuntimeError("boom")
        return CheckResult(stream_id=stream.stream_id, probe_location="test", http_status=200)

    monkeypatch.setattr(scheduler, "check_stream", flaky)
    results = await run_checks(
        streams,
        client=None,  # type: ignore[arg-type]  # check_stream замокан, клиент не нужен
        settings=AppSettings(),
    )

    assert len(results) == 3
    failed = [r for r in results if r.error_code == CheckErrorCode.UNKNOWN]
    assert len(failed) == 1
    assert failed[0].stream_id == broken_id
    assert "RuntimeError" in (failed[0].error_message or "")
    ok = [r for r in results if r.error_code is None]
    assert {r.stream_id for r in ok} == {streams[0].stream_id, streams[2].stream_id}


@pytest.mark.asyncio
async def test_all_results_have_stream_id(monkeypatch) -> None:
    """Каждый входной поток даёт результат — порядок входа сохраняется."""
    streams = [_stream(0), _stream(1)]

    async def always_fail(stream, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise ValueError(stream.url)

    monkeypatch.setattr(scheduler, "check_stream", always_fail)
    results = await run_checks(streams, client=None, settings=AppSettings())  # type: ignore[arg-type]

    assert [r.stream_id for r in results] == [s.stream_id for s in streams]
    assert all(r.error_code == CheckErrorCode.UNKNOWN for r in results)
