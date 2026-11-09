"""Дедупликация каналов и потоков."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..domain.channel import Channel
from ..domain.stream import Stream
from .channel_names import normalize_name


def merge_key(channel: Channel) -> tuple[str, str]:
    """Ключ слияния: нормализованное название + страна.

    Безымянные каналы (normalize_name == "") не схлопываются в один
    (issue #26) — они обрабатываются в deduplicate отдельным ключом.
    """
    return (normalize_name(channel.name), channel.country)


def normalize_stream_url(url: str) -> str:
    """Каноническая форма URL для дедупликации (issue #26).

    scheme/host в нижнем регистре, default-порт снят, завершающий слэш
    пути убран, query-параметры отсортированы. ``http://H/a.m3u8`` и
    ``https://h/a.m3u8/`` при этом различаются схемой — реально разные
    адреса. stream_id остаётся sha256 сырого URL: история стабильна.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower() or "http"
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        port = None
    default_port = {"http": 80, "https": 443}.get(scheme)
    netloc = host if port in (None, default_port) else f"{host}:{port}"
    if parts.username:
        userinfo = parts.username
        if parts.password:
            userinfo += f":{parts.password}"
        netloc = f"{userinfo}@{netloc}"
    path = parts.path.rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((scheme, netloc, path, query, parts.fragment))


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
    for index, channel in enumerate(channels):
        name_key = normalize_name(channel.name)
        if name_key:
            key = (name_key, channel.country)
        else:
            # Безымянные каналы не сливаются в одну сущность (issue #26):
            # индекс входа детерминирован при том же порядке discovery.
            key = (f"@unnamed:{index}", channel.country)
        groups.setdefault(key, []).append(channel)

    canonical: dict[str, str] = {}  # старый channel_id -> канонический channel_id
    merged_channels: list[Channel] = []
    used_channel_ids: set[str] = set()
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
        if merged.channel_id in used_channel_ids:
            # Безымянные каналы получают slug «-channel» — коллизию id
            # разрешаем детерминированным суффиксом (issue #26).
            merged = merged.model_copy(
                update={"channel_id": f"{merged.country.lower()}-unnamed-{len(merged_channels)}"}
            )
        used_channel_ids.add(merged.channel_id)
        merged_channels.append(merged)
        for variant in variants:
            canonical[variant.channel_id] = merged.channel_id

    known_ids = {c.channel_id for c in merged_channels}
    seen_urls: set[str] = set()
    merged_streams: list[Stream] = []
    for stream in streams:
        target = canonical.get(stream.channel_id, stream.channel_id)
        if target not in known_ids:
            continue  # поток без канала — пропускаем
        url_key = normalize_stream_url(stream.url)
        if url_key in seen_urls:
            continue
        seen_urls.add(url_key)
        if target != stream.channel_id:
            merged_streams.append(stream.model_copy(update={"channel_id": target}))
        else:
            merged_streams.append(stream)

    return merged_channels, merged_streams
