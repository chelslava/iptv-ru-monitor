"""Жизненный цикл потока: провалы подряд и автодеградация (issue #8).

Подтверждение к публикации — одностороннее действие, а источники умирают
за часы (домашний ночной прогон даёт ~32% провалов). Чтобы плейлист не
гнил, поток с N провалами подряд (по всем точкам наблюдения) помечается
stale, с 2N — автоматически запрещается к публикации. Один успех
сбрасывает счётчик: поток реанимируется без ручного вмешательства, а
approved-запись review-источника не удаляется (возврат через кандидатов).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.check_result import CheckResult


@dataclass
class StreamLifecycle:
    """Состояние потока по последним проверкам."""

    stream_id: str
    consecutive_failures: int
    stale: bool
    denied: bool


def analyze_lifecycle(
    results: list[CheckResult],
    *,
    stale_after: int,
    deny_after: int,
) -> StreamLifecycle:
    """Посчитать провалы подряд от самой свежей проверки до первого успеха.

    Порядок результатов не гарантирован хранилищем — сортируем по
    checked_at по возрастанию и считаем от конца.
    """
    ordered = sorted(results, key=lambda r: r.checked_at)
    failures = 0
    for result in reversed(ordered):
        if result.is_success():
            break
        failures += 1
    return StreamLifecycle(
        stream_id=ordered[-1].stream_id if ordered else "",
        consecutive_failures=failures,
        stale=stale_after > 0 and failures >= stale_after,
        denied=deny_after > 0 and failures >= deny_after,
    )
