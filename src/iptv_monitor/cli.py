"""CLI iptv-monitor: этапы конвейера мониторинга IPTV."""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import click
import httpx

from . import __version__
from .checking import apply_rotation, flussonic_catchup_source, parse_levels, run_checks
from .checking.geo import detect_country_code
from .discovery import create_adapter, fetch_all
from .domain.channel import Channel
from .domain.check_result import CheckResult, now_utc
from .domain.enums import MatchMethod
from .domain.stream import Stream
from .filtering import (
    ApprovalCandidate,
    PublishDecision,
    best_per_channel,
    candidates_to_dicts,
    decide_publication,
    find_candidates,
    load_approved_ids,
    order_streams_for_approval,
    select_streams,
)
from .filtering.country_profiles import SelectedStream
from .generators import (
    assign_channel_numbers,
    build_report,
    build_stats,
    channels_catalog,
    entry_for,
    render_index_html,
    render_m3u,
    render_xmltv,
    streams_catalog,
    write_json,
)
from .history.lifecycle import analyze_lifecycle
from .history.retention import prune_storage
from .infrastructure.atomic import atomic_write_text
from .infrastructure.http_client import create_client
from .infrastructure.logging import setup_logging
from .infrastructure.storage import JsonlStorage, SqliteStorage, create_storage
from .metadata import (
    AliasIndex,
    EpgProgramme,
    match_epg,
    match_logos,
    namespace_epg,
    parse_channels_csv,
    parse_xmltv_channels,
    parse_xmltv_programmes,
    validate_logo,
)
from .normalization import normalize_discovered
from .normalization.deduplication import deduplicate
from .scoring import StreamScore, best_height, score_stream
from .settings import (
    AliasRule,
    AppSettings,
    available_countries,
    load_categories,
    load_country,
    load_epg_sources,
    load_logo_sources,
    load_name_bridge,
    load_quality,
    load_settings,
    load_sources,
)

logger = logging.getLogger(__name__)

STATE_CHANNELS = "channels.json"
STATE_STREAMS = "streams.json"
STATE_SCORES = "scores.json"
STATE_CANDIDATES = "candidates.json"
STATE_EPG_MATCHES = "epg_matches.json"
STATE_EPG_PROGRAMMES = "epg_programmes.json"


# --- Настройки и состояние ---------------------------------------------------


def _apply_overrides(
    settings: AppSettings,
    *,
    data_dir: Path | None,
    dist_dir: Path | None,
    probe_location: str | None,
) -> AppSettings:
    if data_dir:
        settings = settings.model_copy(
            update={"paths": settings.paths.model_copy(update={"data_dir": data_dir})}
        )
    if dist_dir:
        settings = settings.model_copy(
            update={"paths": settings.paths.model_copy(update={"dist_dir": dist_dir})}
        )
    if probe_location:
        settings = settings.model_copy(update={"probe_location": probe_location})
    return settings


def _state_path(settings: AppSettings, filename: str) -> Path:
    return settings.state_dir / filename


def _save_state(settings: AppSettings, filename: str, payload: object) -> None:
    write_json(_state_path(settings, filename), payload)


def _load_state(settings: AppSettings, filename: str) -> Any:
    path = _state_path(settings, filename)
    if not path.is_file():
        raise click.ClickException(f"state file not found: {path}; run discover first")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_channels(settings: AppSettings) -> list[Channel]:
    return [Channel.model_validate(item) for item in _load_state(settings, STATE_CHANNELS)]


def _load_streams(settings: AppSettings) -> list[Stream]:
    return [Stream.model_validate(item) for item in _load_state(settings, STATE_STREAMS)]


# --- Этапы конвейера ---------------------------------------------------------


def run_discover(
    settings: AppSettings, client: httpx.AsyncClient | None = None
) -> tuple[list[Channel], list[Stream]]:
    """Собрать источники, нормализовать и дедуплицировать каталог."""
    sources = load_sources(settings.config_dir)
    categories = load_categories(settings.config_dir)
    adapters = [create_adapter(s) for s in sources if s.enabled]
    if not adapters:
        click.echo("Нет включённых источников (config/sources.yaml).")
        return [], []

    async def _fetch() -> list:
        if client is not None:
            return await fetch_all(adapters, client)
        async with create_client(
            user_agent=settings.check.user_agent,
            timeout_seconds=settings.check.http_timeout_seconds,
        ) as own:
            return await fetch_all(adapters, own)

    discovered = asyncio.run(_fetch())
    channels, streams = normalize_discovered(discovered, sources, categories)
    channels, streams = deduplicate(channels, streams)

    _save_state(settings, STATE_CHANNELS, [c.model_dump(mode="json") for c in channels])
    _save_state(settings, STATE_STREAMS, [s.model_dump(mode="json") for s in streams])
    click.echo(
        f"Discovery: {len(discovered)} записей -> {len(channels)} каналов, "
        f"{len(streams)} потоков (дублей устранено: {len(discovered) - len(streams)})"
    )
    return channels, streams


def run_check(
    settings: AppSettings,
    *,
    levels: tuple[str, ...],
    limit: int | None = None,
    stream_id: str | None = None,
    probe_location: str | None = None,
    country_code: str | None = None,
    rotate_offset: int | None = None,
    rotate_parts: int | None = None,
    order: str = "catalog",
    client: httpx.AsyncClient | None = None,
) -> list[CheckResult]:
    """Проверить потоки и записать историю в хранилище."""
    streams = _load_streams(settings)
    if stream_id:
        streams = [s for s in streams if s.stream_id == stream_id]
        if not streams:
            raise click.ClickException(f"stream not found: {stream_id}")
    streams = [s for s in streams if s.enabled]
    if order == "approval" and stream_id is None:
        # Приоритетная очередь (волна 3): готовые к кандидату потоки — из
        # ВСЕГО каталога (сегмент есть, второй точки наблюдения нет);
        # хвост — ротационный срез (issues #16, #17). Пока готовые не
        # исчерпаются, ротация дозирует только хвост.
        storage = create_storage(settings)
        grouped: dict[str, list[CheckResult]] = {}
        for result in storage.load():
            grouped.setdefault(result.stream_id, []).append(result)
        storage.close()
        approved = load_approved_ids(settings.state_dir)
        ready = order_streams_for_approval(
            streams, grouped, approved, probe_location=probe_location
        )
        ready_ids = {s.stream_id for s in ready}
        tail = streams
        if rotate_parts is not None and rotate_parts > 1:
            try:
                tail = apply_rotation(streams, rotate_offset or 0, rotate_parts)
            except ValueError as exc:
                raise click.ClickException(str(exc)) from exc
        streams = ready + [s for s in tail if s.stream_id not in ready_ids]
        click.echo(f"Очередь approval: готовых {len(ready)}, хвост {len(streams) - len(ready)}")
    elif rotate_parts is not None and rotate_parts > 1 and stream_id is None:
        # Ротация каталога (issues #16, #17): срез до лимита — лимит лишь
        # ограничивает объём работы внутри уже выбранного среза.
        try:
            streams = apply_rotation(streams, rotate_offset or 0, rotate_parts)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    if limit:
        streams = streams[:limit]
    if not streams:
        click.echo("Нет потоков для проверки.")
        return []

    total = len(streams)
    storage = create_storage(settings)
    # Инкрементальная запись истории (issue #19): результаты сбрасываются
    # в хранилище батчами по мере завершения проверок — падение процесса
    # не теряет уже выполненную работу.
    pending: list[CheckResult] = []
    flush_every = 250

    def _flush() -> None:
        if pending:
            storage.append(pending)
            pending.clear()

    def _progress(done: int, result: CheckResult) -> None:
        if done == total or done % 25 == 0:
            status = "ok" if result.is_success() else f"FAIL ({result.error_code})"
            click.echo(f"  [{done}/{total}] {result.stream_id}: {status}")
        pending.append(result)
        if len(pending) >= flush_every:
            _flush()

    async def _run() -> list[CheckResult]:
        if client is not None:
            return await _run_with_client(client)
        async with create_client(
            user_agent=settings.check.user_agent,
            timeout_seconds=settings.check.http_timeout_seconds,
        ) as own:
            return await _run_with_client(own)

    async def _run_with_client(active: httpx.AsyncClient) -> list[CheckResult]:
        resolved_country = country_code
        if resolved_country is None and settings.geo.ip_info_url:
            resolved_country = await detect_country_code(active, settings.geo.ip_info_url)
        # Скоуп DVR-пробы (issue #10): «approved» — только подтверждённые
        # и опубликованные потоки (~100 шт.), «all» — все прошедшие HLS.
        dvr_stream_ids: set[str] | None = None
        if settings.check.dvr_probe and settings.check.dvr_probe_scope == "approved":
            dvr_stream_ids = load_approved_ids(settings.state_dir)
        return await run_checks(
            streams,
            active,
            settings,
            levels=levels,
            probe_location=probe_location,
            country_code=resolved_country,
            progress=_progress,
            dvr_stream_ids=dvr_stream_ids,
        )

    try:
        results = asyncio.run(_run())
    finally:
        _flush()
        storage.close()

    ok = sum(1 for r in results if r.is_success())
    errors = Counter(r.error_code.value for r in results if r.error_code)
    click.echo(f"Проверка: {ok}/{len(results)} успешно; ошибки: {dict(errors.most_common(5))}")
    return results


def run_enrich(settings: AppSettings) -> dict[str, int]:
    """Сопоставить EPG и логотипы, обновить каталог каналов."""
    channels = _load_channels(settings)
    epg_sources = [s for s in load_epg_sources(settings.config_dir) if s.enabled]
    logos_cfg = load_logo_sources(settings.config_dir)

    alias_rules: list[AliasRule] = []
    for code in available_countries(settings.config_dir):
        try:
            country_aliases = load_country(settings.config_dir, code).aliases
        except FileNotFoundError:  # pragma: no cover - защита от гонки удаления
            continue
        # Алиасы скоупятся страной профиля (issue #22): RU-правило не
        # срабатывает для одноимённого канала другой страны.
        alias_rules.extend(rule.model_copy(update={"country": code}) for rule in country_aliases)
    aliases = AliasIndex(alias_rules)

    matches: list = []
    programmes: list[EpgProgramme] = []
    validated_logos: list = []
    epg_channels_out: list = []
    bridge = None
    bridge_cfg = load_name_bridge(settings.config_dir)

    async def _fetch() -> None:
        nonlocal matches, programmes, validated_logos, epg_channels_out, bridge
        # EPG-файлы бывают до сотен МБ — таймаут только на соединение.
        async with create_client(
            user_agent=settings.check.user_agent,
            timeout_seconds=10.0,
        ) as client:
            # Мост имён (issue #5): канонические имена/алиасы iptv-org/database
            # расширяют сопоставление с EPG по именам. Ошибка загрузки не
            # фатальна — сопоставление деградирует до обычных правил.
            if bridge_cfg.enabled:
                try:
                    response = await client.get(
                        bridge_cfg.url, follow_redirects=True, timeout=300.0
                    )
                    response.raise_for_status()
                    bridge = parse_channels_csv(response.content.decode("utf-8", errors="replace"))
                    click.echo(f"Мост имён: {len(bridge)} записей базы каналов")
                except (httpx.HTTPError, ValueError):
                    logger.warning("name bridge fetch failed", exc_info=True)

            # Мультиисточниковый EPG (issue #5): источники обрабатываются по
            # порядку конфига; id неймспейсится («epg-pw-ru:7103») — числовые
            # id разных провайдеров сталкиваются. Канал уходит первому
            # источнику, давшему МАТЧ С ПРОГРАММАМИ: если у источника нет
            # передач для канала, канал возвращается в очередь и пробуется
            # следующим (иначе «пустой» матч у epg.pw навсегда крадёт канал
            # у iptvx, у которого программы есть).
            pending = list(channels)
            epg_channels_all: list = []
            for source in epg_sources:
                try:
                    response = await client.get(source.url, follow_redirects=True, timeout=600.0)
                    response.raise_for_status()
                except httpx.HTTPError:
                    logger.warning("EPG source %s failed", source.id, exc_info=True)
                    continue
                # Провайдеры отдают XMLTV gzip-файлом (.xml.gz), а не
                # content-encoding — распаковываем по magic bytes.
                payload = response.content
                if payload[:2] == b"\x1f\x8b":
                    try:
                        payload = gzip.decompress(payload)
                    except OSError:
                        logger.warning("EPG source %s: broken gzip", source.id)
                        continue
                try:
                    epg_channels = parse_xmltv_channels(payload)
                except ET.ParseError:
                    logger.warning("EPG source %s: invalid XMLTV", source.id, exc_info=True)
                    continue
                ns_channels, _ = namespace_epg(source.id, epg_channels, [])
                epg_channels_all.extend(ns_channels)
                click.echo(
                    f"EPG: источник {source.id}, {len(epg_channels)} каналов XMLTV, "
                    f"каналов в очереди {len(pending)}"
                )
                if not epg_channels:
                    continue

                source_matches = match_epg(
                    pending,
                    ns_channels,
                    aliases,
                    bridge=bridge,
                    fuzzy_threshold=settings.epg.fuzzy_threshold,
                    ambiguous=ambiguous,
                )
                if not source_matches:
                    continue
                matched_by_prefix: dict[str, set[str]] = {}
                for m in source_matches:
                    source_id, _, raw = m.tvg_id.partition(":")
                    matched_by_prefix.setdefault(source_id, set()).add(raw)
                try:
                    source_programmes = parse_xmltv_programmes(
                        payload, matched_by_prefix.get(source.id, set())
                    )
                except ET.ParseError:
                    logger.warning("EPG source %s: programmes parse failed", source.id)
                    continue
                _, ns_programmes = namespace_epg(source.id, [], source_programmes)
                programmes.extend(ns_programmes)

                # Матчи без программ бесполезны — канал пробуется в следующем источнике.
                with_programmes = {p.channel for p in ns_programmes}
                useful = [m for m in source_matches if m.tvg_id in with_programmes]
                useless_count = len(source_matches) - len(useful)
                matched_ids = {m.channel_id for m in useful}
                pending = [c for c in pending if c.channel_id not in matched_ids]
                matches.extend(useful)
                if useless_count:
                    click.echo(f"EPG: {source.id}: {useless_count} матчей без программ — в очередь")

            epg_channels_out = epg_channels_all

            # Логотипы: кандидаты проходят проверку доступности/MIME/размера
            # (архитектура §10), непроходимые отбрасываются.
            for logo in logo_matches:
                logo_source = next((s for s in logos_cfg.sources if s.id == logo.source_id), None)
                ok = await validate_logo(
                    client,
                    logo.logo_url,
                    max_bytes=logo_source.max_bytes if logo_source else 2_097_152,
                    allowed_mime=logo_source.allowed_mime if logo_source else [],
                )
                if ok:
                    validated_logos.append(logo)
                else:
                    logger.info("logo rejected: %s", logo.logo_url)

    logo_matches = match_logos(channels, logos_cfg.sources, logos_cfg.overrides)
    # Неоднозначные fuzzy-кандидаты (issue #22): не применяются
    # автоматически, накапливаются для отчёта.
    ambiguous: list[str] = []

    if epg_sources or logo_matches:
        asyncio.run(_fetch())
    else:
        click.echo("EPG: нет включённых источников (config/epg_sources.yaml).")

    by_method = Counter(m.method.value for m in matches)

    # tvg_id применяется безусловно: актуальное сопоставление важнее
    # метаданных discovery (m3u и xmltv должны использовать единые id).
    # Логотипы из EPG: иконка сопоставленного канала достаётся каналу
    # без собственного логотипа (покрытие ~24% после отбрасывания data: URI).
    from .normalization import _normalize_logo_url

    epg_icons_used = 0
    epg_icon_by_id = {c.id: c.icon_url for c in epg_channels_out}
    for match in matches:
        for channel in channels:
            if channel.channel_id != match.channel_id:
                continue
            channel.tvg_id = match.tvg_id
            if not channel.logo_url:
                icon = _normalize_logo_url(epg_icon_by_id.get(match.tvg_id))
                if icon:
                    channel.logo_url = icon
                    epg_icons_used += 1
            break
    for logo in validated_logos:
        for channel in channels:
            if channel.channel_id == logo.channel_id and not channel.logo_url:
                channel.logo_url = logo.logo_url
                break

    _save_state(settings, STATE_CHANNELS, [c.model_dump(mode="json") for c in channels])
    _save_state(
        settings,
        STATE_EPG_MATCHES,
        [
            {
                "channel_id": m.channel_id,
                "tvg_id": m.tvg_id,
                "method": m.method.value,
                "confidence": m.confidence,
                "manual": m.manual,
                "original_name": m.original_name,
            }
            for m in matches
        ],
    )
    _save_state(
        settings,
        STATE_EPG_PROGRAMMES,
        [p.model_dump(mode="json") for p in programmes],
    )
    applied_logos = sum(
        1 for logo in validated_logos if not _channel_logo_existed(channels, logo.channel_id)
    )
    ambiguous_unique = len(set(ambiguous))
    click.echo(
        f"Enrich: EPG-совпадений {len(matches)} ({dict(by_method)}), "
        f"fuzzy-неоднозначных {ambiguous_unique}, "
        f"логотипов прошло проверку {len(validated_logos)} из {len(logo_matches)}, "
        f"добавлено {applied_logos}, иконок из EPG {epg_icons_used}"
    )
    return {
        "epg_matches": len(matches),
        "logos": applied_logos,
        "epg_fuzzy": by_method.get(MatchMethod.FUZZY.value, 0),
        "epg_ambiguous": ambiguous_unique,
    }


def _channel_logo_existed(channels: list[Channel], channel_id: str) -> bool:
    for channel in channels:
        if channel.channel_id == channel_id:
            return bool(channel.logo_url)
    return False


def run_score(settings: AppSettings) -> dict[str, StreamScore]:
    """Рассчитать рейтинг потоков по истории проверок."""
    quality = load_quality(settings.config_dir)
    storage = create_storage(settings)
    history = storage.load()
    storage.close()

    grouped: dict[str, list[CheckResult]] = {}
    for result in history:
        grouped.setdefault(result.stream_id, []).append(result)

    scores = {
        stream_id: score_stream(
            stream_id,
            results,
            weights=quality.weights,
            levels=quality.levels,
            min_checks=settings.scoring.min_checks,
        )
        for stream_id, results in grouped.items()
    }
    _save_state(
        settings,
        STATE_SCORES,
        {
            sid: {
                "score": s.score,
                "level": s.level.value,
                "checks": s.checks,
                "components": vars(s.components),
            }
            for sid, s in scores.items()
        },
    )
    levels = Counter(s.level.value for s in scores.values())
    click.echo(f"Скоринг: {len(scores)} потоков; уровни: {dict(levels)}")
    return scores


def run_candidates(
    settings: AppSettings, *, country: str = "RU", apply_changes: bool = False
) -> list[ApprovalCandidate]:
    """Найти кандидатов на подтверждение публикации по отчётной истории.

    Кандидат: рейтинг и число проверок по критериям config/quality_profiles.yaml
    (approval), успех минимум из двух точек наблюдения, HLS-сегмент получен.
    С --apply кандидаты дописываются в approved_streams.yaml.
    """
    quality = load_quality(settings.config_dir)
    approval = quality.approval
    sources_by_id = {s.id: s for s in load_sources(settings.config_dir)}
    channels = _load_channels(settings)
    streams = _load_streams(settings)
    channels_by_id = {c.channel_id: c for c in channels}
    approved = load_approved_ids(settings.state_dir)

    storage = create_storage(settings)
    history = storage.load()
    storage.close()
    grouped: dict[str, list[CheckResult]] = {}
    for result in history:
        grouped.setdefault(result.stream_id, []).append(result)

    decisions: dict[str, PublishDecision] = {}
    for stream in streams:
        channel = channels_by_id.get(stream.channel_id)
        if channel is not None:
            decisions[stream.stream_id] = decide_publication(
                channel, stream, sources_by_id.get(stream.source_id), approved
            )

    scores = {
        stream.stream_id: score_stream(
            stream.stream_id,
            grouped.get(stream.stream_id, []),
            weights=quality.weights,
            levels=quality.levels,
            min_checks=approval.min_checks,
        )
        for stream in streams
    }

    candidates = find_candidates(
        approval=approval,
        channels=channels,
        streams=streams,
        scores=scores,
        decisions=decisions,
        history=grouped,
        country=country,
    )
    _save_state(settings, STATE_CANDIDATES, candidates_to_dicts(candidates))

    click.echo(
        f"Кандидаты: {len(candidates)} (критерии: score>={approval.min_score}, "
        f"проверок>={approval.min_checks}, точек>={approval.min_probe_locations})"
    )
    for candidate in candidates[:10]:
        click.echo(
            f"  {candidate.channel_name}: score={candidate.score} "
            f"({candidate.level}, проверок {candidate.checks}, "
            f"точки: {','.join(candidate.probe_locations)})"
        )

    if apply_changes and candidates:
        merged = sorted(approved | {c.stream_id for c in candidates})
        path = settings.state_dir / "approved_streams.yaml"
        # Шапка с ручными комментариями сохраняется (issue #26): берём
        # комментарии существующего файла, иначе — дефолтная.
        existing_header: list[str] = []
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("#"):
                    existing_header.append(line)
                elif line.strip():
                    break  # дошли до данных — комментарий закончился
        header = "\n".join(
            existing_header
            or [
                "# Подтверждённые к публикации stream_id (public_policy: review).",
                "# Дополняется автоматически кандидатами (iptv-monitor candidates --apply)",
                "# и вручную; детали — data/state/candidates.json и PR approve-candidates.",
            ]
        )
        header += "\nstream_ids:\n\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, header + "".join(f"  - {sid}\n" for sid in merged))
        click.echo(f"Подтверждено +{len(merged) - len(approved)} (всего {len(merged)})")
    return candidates


def run_build(
    settings: AppSettings, country: str = "RU", only_profile: str | None = None
) -> dict[str, object]:
    """Собрать плейлисты, каталоги и отчёты в dist/."""
    country_profile = load_country(settings.config_dir, country)
    quality = load_quality(settings.config_dir)
    sources_by_id = {s.id: s for s in load_sources(settings.config_dir)}
    channels = _load_channels(settings)
    streams = _load_streams(settings)
    channels_by_id = {c.channel_id: c for c in channels}
    approved = load_approved_ids(settings.state_dir)

    storage = create_storage(settings)
    history = storage.load()
    storage.close()
    grouped: dict[str, list[CheckResult]] = {}
    for result in history:
        grouped.setdefault(result.stream_id, []).append(result)
    heights = {sid: best_height(results) for sid, results in grouped.items()}

    # DVR-состояние потока по последней пробе (issue #10): dvr True/False
    # чередуются — берём значение из самой свежей пробы с непустым полем.
    dvr_by_stream: dict[str, int] = {}
    for sid, results in grouped.items():
        ordered = sorted(results, key=lambda r: r.checked_at)
        hours: int | None = None
        for r in ordered:
            if r.dvr:
                hours = r.dvr_hours or 1
            elif r.dvr is False:
                hours = None
        if hours:
            dvr_by_stream[sid] = hours

    # UA-требование по последней успешной проверке (issue #18): если сервер
    # отдал контент только браузерному User-Agent, в плейлист добавляются
    # директивы #EXTVLCOPT/#KODIPROP (VLC/Kodi); последний успех сбрасывает.
    ua_required_by_stream: dict[str, bool] = {}
    for sid, results in grouped.items():
        ordered = sorted(results, key=lambda r: r.checked_at)
        for r in reversed(ordered):
            if r.is_success():
                if r.ua_required:
                    ua_required_by_stream[sid] = True
                break

    # Жизненный цикл (issue #8): N провалов подряд — stale, 2N — автодeny.
    lifecycle_cfg = settings.lifecycle
    lifecycle = {
        sid: analyze_lifecycle(
            results,
            stale_after=lifecycle_cfg.stale_consecutive_failures,
            deny_after=lifecycle_cfg.deny_consecutive_failures,
        )
        for sid, results in grouped.items()
    }
    stale_count = sum(1 for lc in lifecycle.values() if lc.stale and not lc.denied)
    denied_count = sum(1 for lc in lifecycle.values() if lc.denied)
    if stale_count or denied_count:
        click.echo(f"Жизненный цикл: stale {stale_count}, автодeny {denied_count}")

    decisions: dict[str, PublishDecision] = {}
    for stream in streams:
        channel = channels_by_id.get(stream.channel_id)
        if channel is not None:
            lc = lifecycle.get(stream.stream_id)
            decisions[stream.stream_id] = decide_publication(
                channel,
                stream,
                sources_by_id.get(stream.source_id),
                approved,
                denied_consecutive_failures=(
                    lc.consecutive_failures if lc is not None and lc.denied else None
                ),
            )

    playlists = [
        p for p in country_profile.playlists if only_profile is None or p.profile == only_profile
    ]
    if not playlists:
        raise click.ClickException(f"no playlists to build for profile {only_profile!r}")

    dist_country = settings.dist_dir / country.lower()
    dist_country.mkdir(parents=True, exist_ok=True)
    written: list[dict[str, object]] = []
    default_selection: list[SelectedStream] = []
    default_report: dict[str, object] | None = None

    for index, playlist in enumerate(playlists):
        profile_cfg = quality.profile(playlist.profile)
        scores = {
            stream.stream_id: score_stream(
                stream.stream_id,
                grouped.get(stream.stream_id, []),
                weights=quality.weights,
                levels=quality.levels,
                min_checks=profile_cfg.min_checks,
            )
            for stream in streams
        }
        selected = select_streams(
            profile=profile_cfg,
            channels=channels,
            streams=streams,
            scores=scores,
            decisions=decisions,
            best_heights=heights,
        )
        included = best_per_channel([sel for sel in selected if sel.included])
        entries = [entry_for(sel.channel, sel.stream) for sel in included]
        # Catchup-атрибуты для потоков с подтверждённым DVR (issue #10).
        for sel, entry in zip(included, entries, strict=True):
            hours = dvr_by_stream.get(sel.stream.stream_id)
            if hours:
                entry.catchup = "flussonic"
                entry.catchup_days = hours
                entry.catchup_source = flussonic_catchup_source(sel.stream.url)
            # UA-директивы для потоков, требующих браузерный UA (issue #18).
            if ua_required_by_stream.get(sel.stream.stream_id):
                entry.http_user_agent = settings.check.browser_user_agent
        assign_channel_numbers(entries, overrides=country_profile.channel_numbers)
        atomic_write_text(
            dist_country / playlist.filename,
            render_m3u(entries, epg_url=country_profile.epg_filename),
        )
        if index == 0:
            default_selection = selected
        # Per-profile отчёты (issue #26): report.json — основной профиль,
        # report-<profile>.json — остальные; причины включения/исключения
        # видны для каждого профиля, а не только для дефолтного.
        profile_report = build_report(
            country=country,
            profile_id=playlist.profile,
            selections=selected,
            results=history,
            generated_at=now_utc(),
            lifecycle=lifecycle,
        )
        if index == 0:
            default_report = profile_report
        report_name = "report.json" if index == 0 else f"report-{playlist.profile}.json"
        write_json(dist_country / report_name, profile_report)
        written.append(
            {
                "title": playlist.title or playlist.filename,
                "filename": playlist.filename,
                "url": f"{country.lower()}/{playlist.filename}",
                "included": len(included),
            }
        )
        click.echo(
            f"Профиль {playlist.profile}: {len(included)}/{len(selected)} потоков -> "
            f"{dist_country / playlist.filename}"
        )

    # Каталоги каналов и потоков.
    country_channels = [c for c in channels if c.country == country]
    write_json(dist_country / "channels.json", channels_catalog(country_channels))
    selection_ids = {s.stream.stream_id for s in default_selection}
    write_json(
        dist_country / "streams.json",
        streams_catalog(
            default_selection,
            ua_required={sid: True for sid in ua_required_by_stream if sid in selection_ids},
        ),
    )

    # XMLTV, если есть сопоставленные программы.
    programmes: list[EpgProgramme] = []
    epg_path = _state_path(settings, STATE_EPG_PROGRAMMES)
    if country_profile.epg_filename and epg_path.is_file():
        with epg_path.open("r", encoding="utf-8") as fh:
            programmes = [EpgProgramme.model_validate(item) for item in json.load(fh)]
        if programmes:
            xmltv_text = render_xmltv(country_channels, programmes)
            atomic_write_text(dist_country / country_profile.epg_filename, xmltv_text)
            click.echo(f"XMLTV: {len(programmes)} программ -> {country_profile.epg_filename}")

    # stats.json и дашборд (issue #9): сводка проекта + покрытие EPG плейлиста.
    included_default = [s for s in default_selection if s.included]
    programme_channels = {p.channel for p in programmes}
    epg_playlist_channels = sum(
        1 for s in included_default if s.channel.tvg_id and s.channel.tvg_id in programme_channels
    )
    stats = build_stats(
        country=country,
        channels_total=len(country_channels),
        selections=default_selection,
        results=history,
        generated_at=now_utc(),
        epg_playlist_channels=epg_playlist_channels,
        lifecycle=lifecycle,
    )
    write_json(dist_country / "stats.json", stats)
    click.echo(
        f"Stats: каталог {stats['catalog']['channels']} каналов, "
        f"плейлист {stats['playlist']['channels']} каналов, "
        f"EPG {epg_playlist_channels}/{stats['playlist']['streams']}"
    )

    # Топ каналов для index.html: по score, uptime — из отчёта основного профиля.
    report_streams: dict[str, dict[str, Any]] = {}
    if default_report is not None:
        report_data = cast(dict[str, Any], default_report)
        report_streams = {str(s["stream_id"]): s for s in report_data["streams"]}
    top_channels = []
    for sel in sorted(
        included_default,
        key=lambda s: -(s.score.score if s.score and s.score.score is not None else -1.0),
    )[:20]:
        report_entry: dict[str, Any] = report_streams.get(sel.stream.stream_id, {})
        top_channels.append(
            {
                "name": sel.channel.name,
                "logo": sel.channel.logo_url,
                "group": sel.channel.category.value,
                "score": report_entry.get("score"),
                "uptime": report_entry.get("uptime_7d_percent"),
            }
        )

    # Индексная страница.
    settings.dist_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        settings.dist_dir / "index.html",
        render_index_html(
            site_title=f"iptv-ru-monitor — {country_profile.name or country}",
            playlists=written,
            report_path=f"{country.lower()}/report.json",
            last_generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
            stats=stats,
            top_channels=top_channels,
            catalog_path=f"{country.lower()}/channels.json",
        ),
        encoding="utf-8",
    )
    return {"written": written}


# --- CLI-команды ---------------------------------------------------------------


@click.group()
@click.version_option(__version__)
@click.option(
    "--config-dir", type=click.Path(path_type=Path), default=None, envvar="IPTV_CONFIG_DIR"
)
@click.option("--data-dir", type=click.Path(path_type=Path), default=None, envvar="IPTV_DATA_DIR")
@click.option("--dist-dir", type=click.Path(path_type=Path), default=None, envvar="IPTV_DIST_DIR")
@click.option("--probe-location", default=None, envvar="IPTV_PROBE_LOCATION")
@click.option("-v", "--verbose", count=True, help="Подробнее (-vv — отладка).")
@click.pass_context
def cli(
    ctx: click.Context,
    config_dir: Path | None,
    data_dir: Path | None,
    dist_dir: Path | None,
    probe_location: str | None,
    verbose: int,
) -> None:
    """iptv-ru-monitor — мониторинг публичных IPTV-потоков."""
    settings = load_settings(config_dir)
    settings = _apply_overrides(
        settings, data_dir=data_dir, dist_dir=dist_dir, probe_location=probe_location
    )
    level = "DEBUG" if verbose >= 2 else ("INFO" if verbose == 1 else settings.app.log_level)
    setup_logging(level)
    ctx.obj = settings


@cli.command()
@click.pass_obj
def discover(settings: AppSettings) -> None:
    """Собрать и нормализовать каталог из источников."""
    run_discover(settings)


@cli.command()
@click.option("--levels", default="http,hls", help="Уровни: http,hls,ffprobe,playback")
@click.option("--limit", type=int, default=None, help="Проверить первые N потоков")
@click.option("--stream-id", default=None, help="Проверить один поток")
@click.option("--probe-location", default=None, help="Метка точки наблюдения")
@click.option("--country", "country_code", default=None, help="Страна точки наблюдения (ISO)")
@click.option(
    "--rotate-offset",
    type=int,
    default=None,
    help="Слот ротации каталога (0 <= offset < rotate-parts); с --stream-id игнорируется",
)
@click.option(
    "--rotate-parts",
    type=int,
    default=None,
    help="Число слотов ротации; >= 2 включает stride-срез каталога (issues #16/#17)",
)
@click.option(
    "--order",
    type=click.Choice(["catalog", "approval"]),
    default="catalog",
    help="catalog — порядок каталога; approval — готовые к кандидату первыми (волна 3)",
)
@click.pass_obj
def check(
    settings: AppSettings,
    levels: str,
    limit: int | None,
    stream_id: str | None,
    probe_location: str | None,
    country_code: str | None,
    rotate_offset: int | None,
    rotate_parts: int | None,
    order: str,
) -> None:
    """Проверить потоки и записать историю."""
    run_check(
        settings,
        levels=parse_levels(levels),
        limit=limit,
        stream_id=stream_id,
        probe_location=probe_location,
        country_code=country_code,
        rotate_offset=rotate_offset,
        rotate_parts=rotate_parts,
        order=order,
    )


@cli.command()
@click.pass_obj
def enrich(settings: AppSettings) -> None:
    """Сопоставить EPG и логотипы."""
    run_enrich(settings)


@cli.command()
@click.pass_obj
def score(settings: AppSettings) -> None:
    """Рассчитать рейтинг потоков по истории."""
    run_score(settings)


@cli.command("candidates")
@click.option("--country", default="RU", help="Код страны.")
@click.option("--apply", is_flag=True, help="Дописать кандидатов в approved_streams.yaml.")
@click.pass_obj
def candidates_cmd(settings: AppSettings, country: str, apply: bool) -> None:
    """Кандидаты на подтверждение публикации (см. quality_profiles.yaml -> approval)."""
    run_candidates(settings, country=country, apply_changes=apply)


@cli.command()
@click.option("--country", default="RU", help="Код страны (файл config/countries).")
@click.option("--profile", default=None, help="Собрать только указанный профиль.")
@click.pass_obj
def build(settings: AppSettings, country: str, profile: str | None) -> None:
    """Собрать плейлисты и отчёты в dist/."""
    run_build(settings, country=country, only_profile=profile)


@cli.command()
@click.pass_obj
def retention(settings: AppSettings) -> None:
    """Применить политику хранения истории."""
    storage = create_storage(settings)
    if not isinstance(storage, (JsonlStorage, SqliteStorage)):
        raise click.ClickException(f"retention is not supported for {type(storage).__name__}")
    dropped = prune_storage(
        storage,
        history_days=settings.retention.history_days,
        max_results_per_stream=settings.retention.max_results_per_stream,
    )
    storage.close()
    click.echo(f"Retention: удалено записей {dropped}")


@cli.command()
@click.option("--levels", default="http,hls", help="Уровни проверки.")
@click.option("--country", default="RU", help="Страна сборки.")
@click.pass_obj
def pipeline(settings: AppSettings, levels: str, country: str) -> None:
    """Полный цикл: discover → check → enrich → score → retention → candidates → build."""
    run_discover(settings)
    run_check(settings, levels=parse_levels(levels))
    run_enrich(settings)
    run_score(settings)
    # Retention и кандидаты — часть полного цикла (issue #26): без них
    # локальный прогон накапливает историю бесконечно и не готовит
    # кандидатов на подтверждение.
    storage = create_storage(settings)
    if not isinstance(storage, (JsonlStorage, SqliteStorage)):
        raise click.ClickException(f"retention is not supported for {type(storage).__name__}")
    dropped = prune_storage(
        storage,
        history_days=settings.retention.history_days,
        max_results_per_stream=settings.retention.max_results_per_stream,
    )
    storage.close()
    click.echo(f"Retention: удалено записей {dropped}")
    run_candidates(settings, country=country)
    run_build(settings, country=country)


@cli.command("countries")
@click.pass_obj
def countries(settings: AppSettings) -> None:
    """Список стран с профилями."""
    for code in available_countries(settings.config_dir):
        try:
            profile = load_country(settings.config_dir, code)
        except FileNotFoundError:  # pragma: no cover
            continue
        playlists = ", ".join(p.profile for p in profile.playlists)
        click.echo(f"{code} — {profile.name or '?'} (профили: {playlists})")


if __name__ == "__main__":
    cli()
