"""CLI iptv-monitor: этапы конвейера мониторинга IPTV."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import click
import httpx

from . import __version__
from .checking import parse_levels, run_checks
from .checking.geo import detect_country_code
from .discovery import create_adapter, fetch_all
from .domain.channel import Channel
from .domain.check_result import CheckResult, now_utc
from .domain.stream import Stream
from .filtering import (
    ApprovalCandidate,
    PublishDecision,
    candidates_to_dicts,
    decide_publication,
    find_candidates,
    load_approved_ids,
    select_streams,
)
from .filtering.country_profiles import SelectedStream
from .generators import (
    build_report,
    channels_catalog,
    entry_for,
    render_index_html,
    render_m3u,
    render_xmltv,
    streams_catalog,
    write_json,
)
from .history.retention import prune_storage
from .infrastructure.http_client import create_client
from .infrastructure.logging import setup_logging
from .infrastructure.storage import JsonlStorage, SqliteStorage, create_storage
from .metadata import AliasIndex, EpgProgramme, match_epg, match_logos, parse_xmltv
from .normalization import normalize_discovered
from .normalization.deduplication import deduplicate
from .scoring import StreamScore, best_height, score_stream
from .settings import (
    AppSettings,
    available_countries,
    load_categories,
    load_country,
    load_epg_sources,
    load_logo_sources,
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
    client: httpx.AsyncClient | None = None,
) -> list[CheckResult]:
    """Проверить потоки и записать историю в хранилище."""
    streams = _load_streams(settings)
    if stream_id:
        streams = [s for s in streams if s.stream_id == stream_id]
        if not streams:
            raise click.ClickException(f"stream not found: {stream_id}")
    streams = [s for s in streams if s.enabled]
    if limit:
        streams = streams[:limit]
    if not streams:
        click.echo("Нет потоков для проверки.")
        return []

    total = len(streams)

    def _progress(done: int, result: CheckResult) -> None:
        if done == total or done % 25 == 0:
            status = "ok" if result.is_success() else f"FAIL ({result.error_code})"
            click.echo(f"  [{done}/{total}] {result.stream_id}: {status}")

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
        return await run_checks(
            streams,
            active,
            settings,
            levels=levels,
            probe_location=probe_location,
            country_code=resolved_country,
            progress=_progress,
        )

    results = asyncio.run(_run())
    storage = create_storage(settings)
    storage.append(results)
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

    alias_rules = []
    for code in available_countries(settings.config_dir):
        try:
            alias_rules.extend(load_country(settings.config_dir, code).aliases)
        except FileNotFoundError:  # pragma: no cover - защита от гонки удаления
            continue
    aliases = AliasIndex(alias_rules)

    matches: list = []
    programmes: list[EpgProgramme] = []

    async def _fetch() -> None:
        nonlocal matches, programmes
        async with create_client(
            user_agent=settings.check.user_agent,
            timeout_seconds=settings.check.http_timeout_seconds,
        ) as client:
            for source in epg_sources:
                try:
                    response = await client.get(source.url, follow_redirects=True)
                    response.raise_for_status()
                except httpx.HTTPError:
                    logger.warning("EPG source %s failed", source.id, exc_info=True)
                    continue
                try:
                    epg_channels, programmes = parse_xmltv(response.text)
                except ValueError:
                    logger.warning("EPG source %s: invalid XMLTV", source.id)
                    continue
                matches = match_epg(channels, epg_channels, aliases)
                click.echo(f"EPG: источник {source.id}, {len(epg_channels)} каналов XMLTV")
                break

    if epg_sources:
        asyncio.run(_fetch())
    else:
        click.echo("EPG: нет включённых источников (config/epg_sources.yaml).")

    logo_matches = match_logos(channels, logos_cfg.sources, logos_cfg.overrides)
    by_method = Counter(m.method.value for m in matches)

    for match in matches:
        for channel in channels:
            if channel.channel_id == match.channel_id and not channel.tvg_id:
                channel.tvg_id = match.tvg_id
                break
    for logo in logo_matches:
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
    click.echo(
        f"Enrich: EPG-совпадений {len(matches)} ({dict(by_method)}), "
        f"логотипов добавлено {len(logo_matches)}"
    )
    return {"epg_matches": len(matches), "logos": len(logo_matches)}


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
        header = "\n".join(
            [
                "# Подтверждённые к публикации stream_id (public_policy: review).",
                "# Дополняется автоматически кандидатами (iptv-monitor candidates --apply)",
                "# и вручную; детали — data/state/candidates.json и PR approve-candidates.",
                "stream_ids:",
                "",
            ]
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(header + "".join(f"  - {sid}\n" for sid in merged), encoding="utf-8")
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

    decisions: dict[str, PublishDecision] = {}
    for stream in streams:
        channel = channels_by_id.get(stream.channel_id)
        if channel is not None:
            decisions[stream.stream_id] = decide_publication(
                channel, stream, sources_by_id.get(stream.source_id), approved
            )

    storage = create_storage(settings)
    history = storage.load()
    storage.close()
    grouped: dict[str, list[CheckResult]] = {}
    for result in history:
        grouped.setdefault(result.stream_id, []).append(result)
    heights = {sid: best_height(results) for sid, results in grouped.items()}

    playlists = [
        p for p in country_profile.playlists if only_profile is None or p.profile == only_profile
    ]
    if not playlists:
        raise click.ClickException(f"no playlists to build for profile {only_profile!r}")

    dist_country = settings.dist_dir / country.lower()
    dist_country.mkdir(parents=True, exist_ok=True)
    written: list[dict[str, object]] = []
    default_selection: list[SelectedStream] = []

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
        included = [sel for sel in selected if sel.included]
        entries = [entry_for(sel.channel, sel.stream) for sel in included]
        (dist_country / playlist.filename).write_text(
            render_m3u(entries, epg_url=country_profile.epg_filename),
            encoding="utf-8",
        )
        if index == 0:
            default_selection = selected
            report = build_report(
                country=country,
                profile_id=playlist.profile,
                selections=selected,
                results=history,
                generated_at=now_utc(),
            )
            write_json(dist_country / "report.json", report)
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
    write_json(dist_country / "streams.json", streams_catalog(default_selection))

    # XMLTV, если есть сопоставленные программы.
    epg_path = _state_path(settings, STATE_EPG_PROGRAMMES)
    if country_profile.epg_filename and epg_path.is_file():
        with epg_path.open("r", encoding="utf-8") as fh:
            programmes = [EpgProgramme.model_validate(item) for item in json.load(fh)]
        if programmes:
            xmltv_text = render_xmltv(country_channels, programmes)
            (dist_country / country_profile.epg_filename).write_text(xmltv_text, encoding="utf-8")
            click.echo(f"XMLTV: {len(programmes)} программ -> {country_profile.epg_filename}")

    # Индексная страница.
    settings.dist_dir.mkdir(parents=True, exist_ok=True)
    (settings.dist_dir / "index.html").write_text(
        render_index_html(
            site_title=f"iptv-ru-monitor — {country_profile.name or country}",
            playlists=written,
            report_path=f"{country.lower()}/report.json",
            last_generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
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
@click.pass_obj
def check(
    settings: AppSettings,
    levels: str,
    limit: int | None,
    stream_id: str | None,
    probe_location: str | None,
    country_code: str | None,
) -> None:
    """Проверить потоки и записать историю."""
    run_check(
        settings,
        levels=parse_levels(levels),
        limit=limit,
        stream_id=stream_id,
        probe_location=probe_location,
        country_code=country_code,
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
    """Полный цикл: discover → check → enrich → score → build."""
    run_discover(settings)
    run_check(settings, levels=parse_levels(levels))
    run_enrich(settings)
    run_score(settings)
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
