"""Базовый интерфейс хранилища результатов проверок."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime

from ...domain.check_result import CheckResult


class CheckStorage(ABC):
    """Хранилище истории CheckResult (SQLite, JSONL, ...)."""

    @abstractmethod
    def append(self, results: Sequence[CheckResult]) -> None:
        """Сохранить результаты проверок."""

    @abstractmethod
    def load(
        self,
        *,
        stream_id: str | None = None,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[CheckResult]:
        """Загрузить историю (при limit — последние по времени)."""

    @abstractmethod
    def close(self) -> None:
        """Освободить ресурсы."""
