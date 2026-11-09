"""SQLite-хранилище истории проверок (основной вариант для VDS)."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from ...domain.check_result import CheckResult, now_utc
from .base import CheckStorage

_SCHEMA = """
CREATE TABLE IF NOT EXISTS check_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stream_id TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    probe_location TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_check_results_stream ON check_results (stream_id, checked_at);
CREATE INDEX IF NOT EXISTS idx_check_results_time ON check_results (checked_at);
"""


class SqliteStorage(CheckStorage):
    """SQLite-хранилище; payload хранится как JSON-представление CheckResult."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def append(self, results: Sequence[CheckResult]) -> None:
        if not results:
            return
        rows = [
            (
                result.stream_id,
                result.checked_at.isoformat(),
                result.probe_location,
                result.model_dump_json(),
            )
            for result in results
        ]
        with self._conn:
            self._conn.executemany(
                "INSERT INTO check_results (stream_id, checked_at, probe_location, payload) "
                "VALUES (?, ?, ?, ?)",
                rows,
            )

    def load(
        self,
        *,
        stream_id: str | None = None,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[CheckResult]:
        query = "SELECT payload FROM check_results WHERE 1=1"
        params: list[object] = []
        if stream_id is not None:
            query += " AND stream_id = ?"
            params.append(stream_id)
        if since is not None:
            query += " AND checked_at >= ?"
            params.append(since.isoformat())
        query += " ORDER BY checked_at"
        if limit is not None:
            query += " DESC LIMIT ?"
            params.append(limit)
        cursor = self._conn.execute(query, params)
        results = [CheckResult.model_validate_json(row[0]) for row in cursor.fetchall()]
        if limit is not None:
            results.reverse()  # хронологический порядок
        return results

    def prune(self, *, history_days: int, max_results_per_stream: int) -> int:
        """Удалить старые записи и сверх лимита на поток. Возвращает число удалённых.

        Оба лимита применяются (issue #26): раньше SQLite-путь игнорировал
        max_results_per_stream — история на VDS росла без ограничения.
        """
        cutoff = (now_utc() - timedelta(days=history_days)).isoformat()
        dropped = 0
        with self._conn:
            cursor = self._conn.execute("DELETE FROM check_results WHERE checked_at < ?", (cutoff,))
            dropped += cursor.rowcount or 0
            cursor = self._conn.execute(
                """
                DELETE FROM check_results WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY stream_id ORDER BY checked_at DESC, id DESC
                        ) AS rn
                        FROM check_results
                    ) WHERE rn > ?
                )
                """,
                (max_results_per_stream,),
            )
            dropped += cursor.rowcount or 0
        return dropped

    def close(self) -> None:
        self._conn.close()
