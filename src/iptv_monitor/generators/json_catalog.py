"""JSON-каталоги: каналы, потоки, вспомогательная запись файлов."""

from __future__ import annotations

import json
from pathlib import Path

from ..domain.channel import Channel
from ..filtering import SelectedStream


def write_json(path: Path, payload: object) -> None:
    """Записать JSON-файл с человекочитаемым форматированием."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def channels_catalog(channels: list[Channel]) -> list[dict[str, object]]:
    """Публичный каталог каналов (без служебных полей)."""
    return [
        {
            "channel_id": channel.channel_id,
            "name": channel.name,
            "alt_names": channel.alt_names,
            "country": channel.country,
            "languages": channel.languages,
            "category": channel.category.value,
            "tvg_id": channel.tvg_id,
            "logo_url": channel.logo_url,
        }
        for channel in channels
    ]


def streams_catalog(
    selections: list[SelectedStream],
    *,
    ua_required: dict[str, bool] | None = None,
) -> list[dict[str, object]]:
    """Публичные сведения о потоках без секретов.

    URL публикуется только для включённых потоков; исключённые записи
    содержат stream_id и причины исключения. ``ua_required`` — потоки,
    которым нужен браузерный User-Agent (issue #18).
    """
    ua_required = ua_required or {}
    return [
        {
            "stream_id": sel.stream.stream_id,
            "channel_id": sel.channel.channel_id,
            "source_id": sel.stream.source_id,
            "protocol": sel.stream.protocol.value,
            "included": sel.included,
            "score": sel.score.score if sel.score else None,
            "level": sel.score.level.value if sel.score else None,
            "url": sel.stream.url if sel.included else None,
            "reasons": sel.reasons or None,
            "ua_required": ua_required.get(sel.stream.stream_id, False),
        }
        for sel in selections
    ]
