"""Поиск кандидатов на подтверждение публикации.

Кандидат — поток review-источника, который:
- заблокирован ТОЛЬКО ожиданием подтверждения (не секретами/запретом);
- набрал рейтинг и число проверок по критериям config/quality_profiles.yaml;
- успешно проверен минимум из двух точек наблюдения;
- хотя бы раз отдал HLS-сегмент.

Человек подтверждает кандидатов merge'ем PR от workflow approve-candidates —
автоматизация готовит предложение, решение остаётся за человеком.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..domain.channel import Channel
from ..domain.check_result import CheckResult
from ..domain.stream import Stream
from ..scoring.quality import StreamScore
from ..settings import ApprovalSettings
from .publication_policy import PublishDecision

_REVIEW_REASONS = ("channel is not public", "awaiting review approval")


@dataclass
class ApprovalCandidate:
    """Кандидат на добавление в approved_streams.yaml."""

    stream_id: str
    channel_id: str
    channel_name: str
    score: float
    level: str
    checks: int
    probe_locations: list[str] = field(default_factory=list)
    segment_ok: bool = False


def _blocked_only_by_review(reasons: list[str]) -> bool:
    """Поток блокирован только review-ожиданием (не секретами и не запретом)."""
    if not reasons:
        return False
    return all(
        reason == _REVIEW_REASONS[0] or reason.startswith(_REVIEW_REASONS[1]) for reason in reasons
    )


def find_candidates(
    *,
    approval: ApprovalSettings,
    channels: list[Channel],
    streams: list[Stream],
    scores: dict[str, StreamScore],
    decisions: dict[str, PublishDecision],
    history: dict[str, list[CheckResult]],
    country: str = "RU",
) -> list[ApprovalCandidate]:
    """Отобрать кандидатов на подтверждение (лучшие сверху, с лимитом)."""
    channels_by_id = {c.channel_id: c for c in channels}
    candidates: list[ApprovalCandidate] = []

    for stream in streams:
        channel = channels_by_id.get(stream.channel_id)
        if channel is None or channel.country != country:
            continue

        decision = decisions.get(stream.stream_id)
        if decision is None:
            continue
        if decision.allowed or not _blocked_only_by_review(decision.reasons):
            continue  # уже публикуется либо блокируется не review-ожиданием

        score = scores.get(stream.stream_id)
        if score is None or score.score is None:
            continue
        if score.level == "insufficient_data" or score.checks < approval.min_checks:
            continue
        if score.score < approval.min_score:
            continue

        results = history.get(stream.stream_id, [])
        success_locations = sorted({r.probe_location for r in results if r.is_success()})
        if len(success_locations) < approval.min_probe_locations:
            continue
        segment_ok = any(r.first_segment_ok for r in results)
        if approval.require_segment and not segment_ok:
            continue

        candidates.append(
            ApprovalCandidate(
                stream_id=stream.stream_id,
                channel_id=stream.channel_id,
                channel_name=channel.name,
                score=score.score,
                level=score.level.value,
                checks=score.checks,
                probe_locations=success_locations,
                segment_ok=segment_ok,
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[: approval.max_per_run]


def candidates_to_dicts(candidates: Iterable[ApprovalCandidate]) -> list[dict[str, object]]:
    """Сериализация кандидатов для candidates.json и тела PR."""
    return [
        {
            "stream_id": c.stream_id,
            "channel_id": c.channel_id,
            "channel": c.channel_name,
            "score": c.score,
            "level": c.level,
            "checks": c.checks,
            "probe_locations": c.probe_locations,
            "segment_ok": c.segment_ok,
        }
        for c in candidates
    ]


def order_streams_for_approval(
    streams: list[Stream],
    grouped: dict[str, list[CheckResult]],
    approved: set[str],
    *,
    probe_location: str | None = None,
) -> list[Stream]:
    """Приоритетная очередь проверок (волна 3, roadmap).

    Tier 1 — потоки, готовые стать кандидатами: успех с сегментом из другой
    точки наблюдения, ещё не подтверждены. Именно им не хватает второй
    точки наблюдения — home-ru закрывает потребность первой же успешной
    проверкой. Сортировка: успешных проверок больше → выше, tie — по
    stream_id (детерминизм).

    Tier 2 — остальные в исходном (ротационном) порядке: покрытие каталога
    продолжается, когда готовые исчерпаны.
    """
    ready: list[Stream] = []
    rest: list[Stream] = []
    for stream in streams:
        if stream.stream_id in approved:
            rest.append(stream)
            continue
        others = [
            r
            for r in grouped.get(stream.stream_id, [])
            if probe_location is None or r.probe_location != probe_location
        ]
        has_segment_elsewhere = any(r.is_success() and r.first_segment_ok for r in others)
        if has_segment_elsewhere:
            ready.append(stream)
        else:
            rest.append(stream)

    def _success_key(stream: Stream) -> tuple[int, str]:
        successes = sum(
            1
            for r in grouped.get(stream.stream_id, [])
            if r.is_success() and (probe_location is None or r.probe_location != probe_location)
        )
        return (-successes, stream.stream_id)

    ready.sort(key=_success_key)
    return ready + rest
