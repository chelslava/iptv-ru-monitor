"""Сопоставление каналов с EPG/XMLTV.

Порядок: точное совпадение tvg_id → ручные алиасы (скоупятся страной) →
нормализованное имя → мост имён iptv-org/database → нечёткое совпадение
(FUZZY, issue #22). Нечёткое совпадение идёт последним и никогда не
перезаписывает ручное подтверждение.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz, process

from ...domain.channel import Channel
from ...domain.enums import MatchMethod
from ...normalization.channel_names import normalize_name
from ..aliases import AliasIndex
from ..name_bridge import NameBridge
from .parser import EpgChannelData

# Имена короче этого числа символов (после нормализации) не участвуют
# в нечётком сопоставлении — слишком много ложных совпадений.
_FUZZY_MIN_NAME_LEN = 4
# Разница топ-2 кандидатов ниже этого числа баллов считается неоднозначной:
# оба с score >= порога и почти одинаково близки к запросу.
_FUZZY_AMBIGUITY_GAP = 10.0


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
    """Индекс display-name -> tvg_id с детерминированным выбором (issue #22).

    Один и тот же display-name может быть у нескольких EPG-каналов —
    побеждает канал, на который ссылается больше display-names; ничья —
    лексикографически меньший id. Раньше setdefault брал первый попавшийся.
    """
    counts: dict[str, dict[str, int]] = {}
    for epg_channel in epg_channels:
        for display_name in epg_channel.display_names:
            key = normalize_name(display_name)
            if not key:
                continue
            per_id = counts.setdefault(key, {})
            per_id[epg_channel.id] = per_id.get(epg_channel.id, 0) + 1
    return {
        key: min(per_id.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        for key, per_id in counts.items()
    }


def _fuzzy_candidates(
    channel: Channel,
    by_norm_name: dict[str, str],
    threshold: float,
) -> tuple[str, str, float, bool] | None:
    """Лучший нечёткий кандидат: (имя канала, tvg_id, score, неоднозначен)."""
    best: tuple[str, str, float, bool] | None = None
    for name in (channel.name, *channel.alt_names):
        norm = normalize_name(name)
        if not norm or len(norm) < _FUZZY_MIN_NAME_LEN:
            continue
        top = process.extract(
            norm,
            list(by_norm_name.keys()),
            scorer=fuzz.token_sort_ratio,
            limit=2,
            score_cutoff=threshold,
        )
        if not top:
            continue
        score = float(top[0][1])
        runner_up = float(top[1][1]) if len(top) > 1 else 0.0
        ambiguous = runner_up >= threshold and score - runner_up < _FUZZY_AMBIGUITY_GAP
        if best is None or score > best[2]:
            best = (name, by_norm_name[top[0][0]], score, ambiguous)
    return best


def match_epg(
    channels: list[Channel],
    epg_channels: list[EpgChannelData],
    aliases: AliasIndex,
    bridge: NameBridge | None = None,
    *,
    fuzzy_threshold: float = 0.0,
    ambiguous: list[str] | None = None,
) -> list[EpgMatch]:
    """Сопоставить каналы с EPG-каналами (см. архитектуру, раздел 10).

    ``fuzzy_threshold`` (0-100, 0 = выключено) включает этап FUZZY;
    неоднозначные кандидаты (два EPG-канала с близким score) не применяются
    автоматически — их channel_id накапливаются в ``ambiguous`` для отчёта.
    """
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

        # 2. Ручные алиасы (не перезаписываются нечётким совпадением),
        # скоупятся страной канала (issue #22).
        # Алиас применим, только если его tvg_id есть в этом EPG-источнике:
        # таблицы алиасов привязаны к формату id конкретного провайдера
        # (например, «1tv.ru» у iptv-org против числовых id epg.pw).
        alias = aliases.lookup(channel.name, *channel.alt_names, country=channel.country)
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
        if bridge is not None:
            bridged = False
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
                    bridged = True
                    break
            if bridged:
                continue

        # 5. Нечёткое совпадение имён (issue #22): rapidfuzz token_sort_ratio
        # с порогом из настроек. Уверенность держится ниже моста (0.7).
        if fuzzy_threshold <= 0:
            continue
        fuzzy = _fuzzy_candidates(channel, by_norm_name, fuzzy_threshold)
        if fuzzy is None:
            continue
        original_name, tvg_id, score, is_ambiguous = fuzzy
        if is_ambiguous:
            if ambiguous is not None:
                ambiguous.append(channel.channel_id)
            continue
        matches.append(
            EpgMatch(
                channel_id=channel.channel_id,
                tvg_id=tvg_id,
                method=MatchMethod.FUZZY,
                confidence=round(min(0.65, score / 100 * 0.75), 2),
                manual=False,
                original_name=original_name,
            )
        )

    return matches
