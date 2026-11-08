"""Репозиторий истории проверок поверх хранилища."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from ..domain.check_result import CheckResult
from ..infrastructure.storage import CheckStorage


class CheckHistoryRepository:
    """Доступ к истории CheckResult с точки наблюдения и без неё."""

    def __init__(self, storage: CheckStorage) -> None:
        self.storage = storage

    def record(self, results: Sequence[CheckResult]) -> None:
        self.storage.append(results)

    def for_stream(self, stream_id: str, *, limit: int | None = None) -> list[CheckResult]:
        return self.storage.load(stream_id=stream_id, limit=limit)

    def all(self, *, since: datetime | None = None) -> list[CheckResult]:
        return self.storage.load(since=since)

    def by_stream(self, *, since: datetime | None = None) -> dict[str, list[CheckResult]]:
        """История, сгруппированная по stream_id (хронологически)."""
        grouped: dict[str, list[CheckResult]] = {}
        for result in self.all(since=since):
            grouped.setdefault(result.stream_id, []).append(result)
        return grouped
