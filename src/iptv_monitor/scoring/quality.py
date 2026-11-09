"""Итоговый рейтинг потока по истории проверок.

Веса — стартовая гипотеза из архитектуры (раздел 9), задаются в
config/quality_profiles.yaml и калибруются по реальным результатам.
Для нового потока с недостаточной историей используется статус
Insufficient data, а не необоснованно высокий балл.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ..domain.check_result import CheckResult
from ..domain.enums import QualityLevel
from ..settings import QualityLevels, QualityWeights
from .availability import availability_score
from .stability import stability_score


@dataclass
class ComponentScores:
    """Значения компонентов рейтинга (None — нет данных)."""

    availability: float | None = None
    stability: float | None = None
    startup: float | None = None
    media: float | None = None
    hls: float | None = None


@dataclass
class StreamScore:
    """Итоговый рейтинг потока."""

    stream_id: str
    checks: int
    score: float | None
    level: QualityLevel
    components: ComponentScores = field(default_factory=ComponentScores)


def startup_score(results: Sequence[CheckResult]) -> float | None:
    """Оценка времени запуска по лучшему результату.

    <=2 с → 100, >=10 с → 0, линейно между.
    """
    startups = [
        r.startup_time_ms for r in results if r.is_success() and r.startup_time_ms is not None
    ]
    if not startups:
        return None
    best_ms = min(startups)
    if best_ms <= 2000:
        return 100.0
    if best_ms >= 10000:
        return 0.0
    return (10000 - best_ms) / 8000 * 100


def media_score(results: Sequence[CheckResult]) -> float | None:
    """Оценка медиапараметров по максимальному известному разрешению."""
    heights = [r.height for r in results if r.is_success() and r.height]
    if not heights:
        return None
    best = max(heights)
    if best >= 1080:
        return 100.0
    if best >= 720:
        return 85.0
    if best >= 576:
        return 65.0
    return 50.0


def hls_correctness_score(results: Sequence[CheckResult]) -> float | None:
    """Доля проверок с корректным HLS playlist."""
    attempts = [r for r in results if r.playlist_ok is not None]
    if not attempts:
        return None
    return sum(1 for r in attempts if r.playlist_ok) / len(attempts) * 100


def best_height(results: Sequence[CheckResult]) -> int | None:
    """Максимальное известное разрешение потока (для профилей качества)."""
    heights = [r.height for r in results if r.height]
    return max(heights) if heights else None


def score_stream(
    stream_id: str,
    results: Sequence[CheckResult],
    *,
    weights: QualityWeights,
    levels: QualityLevels,
    min_checks: int,
) -> StreamScore:
    """Посчитать рейтинг потока по истории.

    Веса нормализуются по компонентам с данными (issue #21): поток,
    проверенный штатным конвейером http,hls (ffprobe выключен), не
    недооценивается из-за отсутствующего media-компонента — его максимум
    остаётся 100, а не 85. Консервативный случай (поток вообще без
    контентных доказательств — только HTTP 200 без попыток HLS) ограничен
    уровнем unstable: без сегмента/плейлиста нельзя считать поток хорошим.
    """
    components = ComponentScores(
        availability=availability_score(results),
        stability=stability_score(results),
        startup=startup_score(results),
        media=media_score(results),
        hls=hls_correctness_score(results),
    )

    if len(results) < min_checks or not results:
        return StreamScore(
            stream_id=stream_id,
            checks=len(results),
            score=None,
            level=QualityLevel.INSUFFICIENT_DATA,
            components=components,
        )

    weight_map = {
        "availability": (components.availability, weights.availability),
        "stability": (components.stability, weights.stability),
        "startup": (components.startup, weights.startup),
        "media": (components.media, weights.media),
        "hls": (components.hls, weights.hls),
    }
    weighted = sum(
        (value if value is not None else 0.0) * weight for value, weight in weight_map.values()
    )
    available_weight = sum(weight for value, weight in weight_map.values() if value is not None)
    # weighted — взвешенная сумма значений 0–100; деление на сумму весов
    # даёт взвешенное среднее на той же шкале 0–100.
    total = weighted / available_weight if available_weight > 0 else 0.0

    # Контентные доказательства: сегмент/плейлист. Только HTTP-успехи
    # (прямой TS, error page с 200) не поднимают поток выше unstable —
    # публикация всё равно требует сегмента (approval.require_segment).
    if components.stability is None and components.hls is None:
        total = min(total, levels.good - 1)

    if total >= levels.excellent:
        level = QualityLevel.EXCELLENT
    elif total >= levels.good:
        level = QualityLevel.GOOD
    elif total >= levels.unstable:
        level = QualityLevel.UNSTABLE
    else:
        level = QualityLevel.FAILED

    return StreamScore(
        stream_id=stream_id,
        checks=len(results),
        score=round(total, 2),
        level=level,
        components=components,
    )
