"""Применение страновых профилей качества к отбору потоков."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.channel import Channel
from ..domain.stream import Stream
from ..scoring.quality import StreamScore
from ..settings import QualityProfileSettings
from .publication_policy import PublishDecision


@dataclass
class SelectedStream:
    """Кандидат на публикацию с решением и причинами.

    Отчёт обязан объяснять, почему поток включён или исключён
    (критерий готовности MVP).
    """

    channel: Channel
    stream: Stream
    score: StreamScore | None = None
    included: bool = False
    reasons: list[str] = field(default_factory=list)


def select_streams(
    *,
    profile: QualityProfileSettings,
    channels: list[Channel],
    streams: list[Stream],
    scores: dict[str, StreamScore],
    decisions: dict[str, PublishDecision],
    best_heights: dict[str, int | None] | None = None,
) -> list[SelectedStream]:
    """Отобрать потоки по профилю качества (min_score, min_height, категории)."""
    best_heights = best_heights or {}
    channels_by_id = {c.channel_id: c for c in channels}
    selected: list[SelectedStream] = []

    for stream in streams:
        channel = channels_by_id.get(stream.channel_id)
        if channel is None:
            continue
        if channel.country != profile.country:
            continue

        score = scores.get(stream.stream_id)
        reasons: list[str] = []

        decision = decisions.get(stream.stream_id)
        if decision is not None:
            reasons.extend(decision.reasons)

        if score is None:
            reasons.append("no check history")
            selected.append(
                SelectedStream(channel=channel, stream=stream, included=False, reasons=reasons)
            )
            continue

        if score.level == "insufficient_data":
            reasons.append(f"insufficient data ({score.checks} checks < {profile.min_checks})")
        elif score.score is not None and score.score < profile.min_score:
            reasons.append(f"score {score.score} below profile minimum {profile.min_score}")

        if profile.categories is not None and channel.category not in profile.categories:
            reasons.append(f"category {channel.category} not in profile")

        if profile.min_height is not None:
            height = best_heights.get(stream.stream_id)
            if height is None or height < profile.min_height:
                reasons.append(
                    f"height {height or 'unknown'} below profile minimum {profile.min_height}"
                )

        included = not reasons
        selected.append(
            SelectedStream(
                channel=channel,
                stream=stream,
                score=score,
                included=included,
                reasons=reasons,
            )
        )

    return selected


def best_per_channel(
    included: list[SelectedStream],
) -> list[SelectedStream]:
    """Один лучший поток на канал — защита от дублей в плейлисте (issue #6).

    Канал дедуплицирован по имени, потоки — нет: один канал может иметь
    несколько прошедших порог потоков из разных источников. В плейлист идёт
    лучший по score (тай-брейки: больше проверок → короче URL → stable id),
    остальные помечаются ``included=False`` с причиной superseded — отчёт
    остаётся объясняющим, а «горячая замена» происходит естественно: при
    падении лучшего потока его score проваливается ниже порога и следующий
    build автоматически поднимает alternate.
    Порядок остальных каналов не меняется.
    """
    by_channel: dict[str, list[SelectedStream]] = {}
    for sel in included:
        by_channel.setdefault(sel.channel.channel_id, []).append(sel)

    best: list[SelectedStream] = []
    for group in by_channel.values():
        if len(group) == 1:
            best.append(group[0])
            continue

        def rank(sel: SelectedStream) -> tuple[float, int, str, str]:
            score = sel.score.score if sel.score and sel.score.score is not None else -1.0
            checks = sel.score.checks if sel.score else 0
            return (-score, -checks, sel.stream.url, sel.stream.stream_id)

        ranked = sorted(group, key=rank)
        winner = ranked[0]
        best.append(winner)
        for loser in ranked[1:]:
            loser.included = False
            loser.reasons.append(
                f"superseded by better stream {winner.stream.stream_id} of the same channel"
            )
    return best
