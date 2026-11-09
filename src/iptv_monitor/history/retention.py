"""Ограничение срока хранения истории проверок."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from ..domain.check_result import CheckResult, now_utc
from ..infrastructure.atomic import atomic_write_text
from ..infrastructure.storage.jsonl import JsonlStorage
from ..infrastructure.storage.sqlite import SqliteStorage


def apply_retention(
    results: list[CheckResult],
    *,
    history_days: int,
    max_results_per_stream: int,
    now: datetime | None = None,
) -> tuple[list[CheckResult], int]:
    """Отфильтровать историю по возрасту и числу записей на поток.

    Возвращает (сохранённые, число отброшенных).
    """
    now = now or now_utc()
    cutoff = now - timedelta(days=history_days)
    kept = [r for r in results if r.checked_at >= cutoff]

    by_stream: dict[str, list[CheckResult]] = defaultdict(list)
    for result in kept:
        by_stream[result.stream_id].append(result)

    final: list[CheckResult] = []
    for stream_results in by_stream.values():
        stream_results.sort(key=lambda r: r.checked_at)
        final.extend(stream_results[-max_results_per_stream:])
    return final, len(results) - len(final)


def prune_storage(
    storage: JsonlStorage | SqliteStorage,
    *,
    history_days: int,
    max_results_per_stream: int,
) -> int:
    """Применить retention к хранилищу на месте. Возвращает число удалённых."""
    if isinstance(storage, JsonlStorage):
        results = storage.load()
        kept, dropped = apply_retention(
            results,
            history_days=history_days,
            max_results_per_stream=max_results_per_stream,
        )
        if dropped:
            # Атомарная перезапись (issue #20): обрыв посреди записи не
            # оставляет урезанный checks.jsonl.
            atomic_write_text(
                storage.path,
                "".join(line + "\n" for line in (r.model_dump_json() for r in kept)),
            )
        return dropped

    if isinstance(storage, SqliteStorage):
        import sqlite3

        cutoff = (now_utc() - timedelta(days=history_days)).isoformat()
        conn: sqlite3.Connection = storage._conn  # noqa: SLF001 - сервисный доступ
        with conn:
            cursor = conn.execute("DELETE FROM check_results WHERE checked_at < ?", (cutoff,))
            dropped = cursor.rowcount or 0
        return dropped

    raise TypeError(f"unsupported storage type: {type(storage).__name__}")
