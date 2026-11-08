"""Дедупликация каналов и потоков."""

from __future__ import annotations

from ..domain.channel import Channel
from ..domain.stream import Stream
from .channel_names import normalize_name


def merge_key(channel: Channel) -> tuple[str, str]:
    """Ключ слияния: нормализованное название + страна."""
    return (normalize_name(channel.name), channel.country)


def deduplicate(
    channels: list[Channel], streams: list[Stream]
) -> tuple[list[Channel], list[Stream]]:
    """Объединить дубликаты каналов и потоки с одинаковыми URL.

    Каналы: одна сущность на (название, страна); первичным становится канал
    с заполненным tvg_id (иначе первый встреченный). Публикация разрешена
    только если она разрешена у всех объединяемых вариантов (консервативно).

    Потоки: уникальность по URL (первый выигрывает), channel_id
    перенаправляется на канонический канал.
    """
    groups: dict[tuple[str, str], list[Channel]] = {}
    for channel in channels:
        groups.setdefault(merge_key(channel), []).append(channel)

    canonical: dict[str, str] = {}  # старый channel_id -> канонический channel_id
    merged_channels: list[Channel] = []
    for variants in groups.values():
        primary = next((c for c in variants if c.tvg_id), variants[0])
        alt_names = sorted(
            {name for c in variants for name in [*c.alt_names, c.name]} - {primary.name}
        )
        languages = sorted({lang for c in variants for lang in c.languages})
        category = next((c.category for c in variants if c.category != "general"), primary.category)
        tvg_id = next((c.tvg_id for c in variants if c.tvg_id), None)
        logo_url = next((c.logo_url for c in variants if c.logo_url), None)
        merged = Channel(
            channel_id=primary.channel_id,
            name=primary.name,
            alt_names=alt_names,
            country=primary.country,
            languages=languages,
            category=category,
            tvg_id=tvg_id,
            logo_url=logo_url,
            # Консервативно: публичным канал остаётся, только если разрешены все варианты.
            is_public=all(c.is_public for c in variants),
            metadata_source=primary.metadata_source,
        )
        merged_channels.append(merged)
        for variant in variants:
            canonical[variant.channel_id] = primary.channel_id

    known_ids = {c.channel_id for c in merged_channels}
    seen_urls: set[str] = set()
    merged_streams: list[Stream] = []
    for stream in streams:
        target = canonical.get(stream.channel_id, stream.channel_id)
        if target not in known_ids:
            continue  # поток без канала — пропускаем
        if stream.url in seen_urls:
            continue
        seen_urls.add(stream.url)
        if target != stream.channel_id:
            merged_streams.append(stream.model_copy(update={"channel_id": target}))
        else:
            merged_streams.append(stream)

    return merged_channels, merged_streams
