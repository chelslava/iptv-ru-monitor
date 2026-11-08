"""Нормализация: превращение сырых записей источников в Channel/Stream."""

from __future__ import annotations

from ..discovery import DiscoveredStream
from ..domain.channel import Channel
from ..domain.enums import PublicPolicy
from ..domain.source import SourceConfig
from ..domain.stream import Stream, detect_protocol, make_stream_id
from ..settings import CategoriesFile
from .categories import classify_channel
from .channel_names import build_channel_id
from .country import normalize_country


def normalize_discovered(
    discovered: list[DiscoveredStream],
    sources: list[SourceConfig],
    categories: CategoriesFile,
) -> tuple[list[Channel], list[Stream]]:
    """Нормализовать записи источников в каналы и потоки.

    Каждая запись связана с источником происхождения (source-first) и
    наследует его страну и политику публикации.
    """
    sources_by_id = {source.id: source for source in sources}
    channels: dict[str, Channel] = {}
    streams: list[Stream] = []

    for entry in discovered:
        source = sources_by_id.get(entry.source_id)
        country = normalize_country(entry.country) or (source.country if source else None)
        if country is None:
            continue  # запись без страны не участвует в каталоге

        name = entry.tvg_name or entry.name
        channel_id = build_channel_id(name, country)
        is_public = bool(source and source.public_policy == PublicPolicy.ALLOW)
        channel = channels.get(channel_id)
        if channel is None:
            channel = Channel(
                channel_id=channel_id,
                name=name,
                alt_names=[entry.name] if entry.tvg_name and entry.name != entry.tvg_name else [],
                country=country,
                languages=[entry.language] if entry.language else [],
                category=classify_channel(
                    name=name,
                    group_title=entry.group_title,
                    rules=categories.rules,
                    default=categories.default_category,
                ),
                tvg_id=entry.tvg_id,
                logo_url=entry.tvg_logo,
                is_public=is_public,
                metadata_source=entry.source_id,
            )
            channels[channel_id] = channel
        elif entry.tvg_id and not channel.tvg_id:
            channel.tvg_id = entry.tvg_id
        if channel.tvg_id and entry.tvg_id and entry.tvg_id != channel.tvg_id:
            pass  # разные tvg_id у дубликатов — решит дедупликация/EPG

        streams.append(
            Stream(
                stream_id=make_stream_id(entry.url),
                channel_id=channel_id,
                url=entry.url,
                protocol=detect_protocol(entry.url),
                source_id=entry.source_id,
            )
        )

    return list(channels.values()), streams
