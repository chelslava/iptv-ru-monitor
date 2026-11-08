"""Компонент рейтинга: доступность при повторных проверках."""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.check_result import CheckResult


def availability_score(results: Sequence[CheckResult]) -> float | None:
    """Доля успешных проверок от общего числа (0–100).

    Успешной считается проверка без классифицированной ошибки.
    """
    if not results:
        return None
    successes = sum(1 for result in results if result.is_success())
    return successes / len(results) * 100
