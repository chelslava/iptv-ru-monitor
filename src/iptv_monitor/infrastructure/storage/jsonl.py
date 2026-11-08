"""JSONL-хранилище истории проверок: одна строка — один CheckResult."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from ...domain.check_result import CheckResult
from .base import CheckStorage

logger = logging.getLogger(__name__)


class JsonlStorage(CheckStorage):
    """Простое файловое хранилище — удобно для артефактов GitHub Actions."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, results: Sequence[CheckResult]) -> None:
        if not results:
            return
        with self.path.open("a", encoding="utf-8") as fh:
            for result in results:
                fh.write(result.model_dump_json() + "\n")

    def load(
        self,
        *,
        stream_id: str | None = None,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[CheckResult]:
        if not self.path.is_file():
            return []
        found: list[CheckResult] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line_number, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    result = CheckResult.model_validate_json(line)
                except ValueError:
                    logger.warning("skip malformed line %d in %s", line_number, self.path)
                    continue
                if stream_id is not None and result.stream_id != stream_id:
                    continue
                if since is not None and result.checked_at < since:
                    continue
                found.append(result)
        found.sort(key=lambda r: r.checked_at)
        return found[-limit:] if limit is not None else found

    def close(self) -> None:
        # Файловые операции выполняются без удержания дескрипторов.
        return
