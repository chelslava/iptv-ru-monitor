"""Тесты ограничения срока хранения истории."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from iptv_monitor.history.retention import apply_retention, prune_storage
from iptv_monitor.infrastructure.storage import JsonlStorage


def test_apply_retention_drops_old_results(make_result) -> None:
    now = datetime.now(UTC)
    fresh = [make_result(checked_at=now - timedelta(days=1))]
    old = [make_result(checked_at=now - timedelta(days=100))]
    kept, dropped = apply_retention(
        fresh + old, history_days=90, max_results_per_stream=100, now=now
    )
    assert kept == fresh
    assert dropped == 1


def test_apply_retention_caps_per_stream(make_result) -> None:
    now = datetime.now(UTC)
    results = [make_result(checked_at=now - timedelta(minutes=i)) for i in range(10)]
    kept, dropped = apply_retention(results, history_days=90, max_results_per_stream=3, now=now)
    assert len(kept) == 3
    assert dropped == 7
    # сохраняются самые свежие
    assert max(r.checked_at for r in kept) == max(r.checked_at for r in results)


def test_prune_jsonl_rewrites_file(tmp_path, make_result) -> None:
    now = datetime.now(UTC)
    storage = JsonlStorage(tmp_path / "checks.jsonl")
    storage.append([make_result(checked_at=now - timedelta(days=200), stream_id="old")])
    storage.append([make_result(checked_at=now, stream_id="new")])
    storage.close()

    storage = JsonlStorage(tmp_path / "checks.jsonl")
    dropped = prune_storage(storage, history_days=90, max_results_per_stream=10)
    assert dropped == 1
    remaining = storage.load()
    assert [r.stream_id for r in remaining] == ["new"]
