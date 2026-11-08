"""Компонент рейтинга: устойчивость получения сегментов и чтения потока."""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.check_result import CheckResult


def stability_score(results: Sequence[CheckResult]) -> float | None:
    """Устойчивость чтения потока (0–100).

    При наличии попыток получения сегмента учитывается доля успешных
    сегментов; иначе — доля валидных media playlist. Единый успешный
    запрос ничего не доказывает: рейтинг строится по всем попыткам.
    """
    segment_attempts = [r for r in results if r.playlist_ok and r.first_segment_ok is not None]
    if segment_attempts:
        successes = sum(1 for r in segment_attempts if r.first_segment_ok)
        return successes / len(segment_attempts) * 100

    playlist_attempts = [r for r in results if r.playlist_ok is not None]
    if playlist_attempts:
        successes = sum(1 for r in playlist_attempts if r.playlist_ok)
        return successes / len(playlist_attempts) * 100

    return None
