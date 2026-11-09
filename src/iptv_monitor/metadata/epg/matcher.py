"""Сопоставление каналов с EPG/XMLTV.

Порядок: точное совпадение tvg_id → ручные алиасы → нормализованное имя →
мост имён iptv-org/database. Нечёткое совпадение (FUZZY) зарезервировано
и никогда не перезаписывает ручное подтверждение.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...domain.channel import Channel
from ...domain.enums import MatchMethod
from ...normalization.channel_names import normalize_name
from ..aliases import AliasIndex
from ..name_bridge import NameBridge
from .parser import EpgChannelData


@dataclass
class EpgMatch:
    """Решение о сопоставлении канала с EPG."""

    channel_id: str
    tvg_id: str
    method: MatchMethod
    confidence: float
    manual: bool
    original_name: str | None = None


def _index_by_normalized_name(
    epg_channels: list[EpgChannelData],
) -> dict[str, str]:
    index: dict[str, str] = {}
    for epg_channel in epg_channels:
        for display_name in epg_channel.display_names:
            index.setdefault(normalize_name(display_name), epg_channel.id)
    return index


def match_epg(
    channels: list[Channel],
    epg_channels: list[EpgChannelData],
    aliases: AliasIndex,
    bridge: NameBridge | None = None,
) -> list[EpgMatch]:
    """Сопоставить каналы с EPG-каналами (см. архитектуру, раздел 10)."""
    epg_ids = {c.id for c in epg_channels}
    by_norm_name = _index_by_normalized_name(epg_channels)
    matches: list[EpgMatch] = []

    for channel in channels:
        # 1. Точное совпадение по tvg_id.
        if channel.tvg_id and channel.tvg_id in epg_ids:
            matches.append(
                EpgMatch(
                    channel_id=channel.channel_id,
                    tvg_id=channel.tvg_id,
                    method=MatchMethod.TVG_ID,
                    confidence=1.0,
                    manual=False,
                    original_name=channel.tvg_id,
                )
            )
            continue

        # 2. Ручные алиасы (не перезаписываются нечётким совпадением).
        # Алиас применим, только если его tvg_id есть в этом EPG-источнике:
        # таблицы алиасов привязаны к формату id конкретного провайдера
        # (например, «1tv.ru» у iptv-org против числовых id epg.pw).
        alias = aliases.lookup(channel.name, *channel.alt_names)
        if alias is not None and alias.tvg_id in epg_ids:
            matches.append(
                EpgMatch(
                    channel_id=channel.channel_id,
                    tvg_id=alias.tvg_id,
                    method=MatchMethod.ALIAS,
                    confidence=0.95,
                    manual=alias.manual,
                    original_name=alias.name,
                )
            )
            continue

        # 3. Нормализованное имя против display-name EPG.
        candidates = [channel.name, *channel.alt_names]
        matched = False
        for name in candidates:
            tvg_id = by_norm_name.get(normalize_name(name))
            if tvg_id:
                matches.append(
                    EpgMatch(
                        channel_id=channel.channel_id,
                        tvg_id=tvg_id,
                        method=MatchMethod.NORMALIZED_NAME,
                        confidence=0.8,
                        manual=False,
                        original_name=name,
                    )
                )
                matched = True
                break
        if matched:
            continue

        # 4. Мост имён iptv-org/database: id формата iptv-org раскрывается
        # в каноническое имя + алиасы (включая русские), которые уже
        # сравниваются с display-name EPG. Слабее собственного имени,
        # потому что алиасы иногда обобщённые.
        if bridge is None:
            continue
        for name in bridge.names_for(channel.tvg_id):
            tvg_id = by_norm_name.get(normalize_name(name))
            if tvg_id:
                matches.append(
                    EpgMatch(
                        channel_id=channel.channel_id,
                        tvg_id=tvg_id,
                        method=MatchMethod.BRIDGE,
                        confidence=0.7,
                        manual=False,
                        original_name=name,
                    )
                )
                break

    return matches
