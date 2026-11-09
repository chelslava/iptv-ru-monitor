"""Оркестрация проверок потоков по уровням.

Проверки выполняются по уровням, чтобы не расходовать ресурсы на тяжёлую
диагностику заведомо неработающих URL: HTTP → HLS → FFprobe → воспроизведение.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable, Sequence

import httpx

from ..domain.check_result import CheckResult
from ..domain.enums import CheckErrorCode, StreamProtocol
from ..domain.stream import Stream
from ..infrastructure.http_client import UrlGuardError, fetch, validate_url
from ..infrastructure.logging import redact_text
from ..settings import AppSettings
from .ffprobe import probe_media
from .geo import resolve_probe_location
from .hls import check_hls, probe_dvr
from .http import classify_http
from .playback import check_playback

logger = logging.getLogger(__name__)

LEVELS = ("http", "hls", "ffprobe", "playback")
DEFAULT_LEVELS: tuple[str, ...] = ("http", "hls")

# Коды ответов, типичные для блока по User-Agent (issue #18):
# 401/403 — авторизация/запрет, 444 — nginx «закрыть без ответа».
_UA_BLOCK_STATUSES = frozenset({401, 403, 444})


def parse_levels(spec: str) -> tuple[str, ...]:
    """Разобрать спецификацию уровней 'http,hls' с проверкой имён."""
    requested = tuple(part.strip() for part in spec.split(",") if part.strip())
    unknown = [level for level in requested if level not in LEVELS]
    if unknown:
        raise ValueError(f"unknown check levels: {unknown}; available: {LEVELS}")
    if not requested:
        raise ValueError("at least one check level is required")
    return requested


def _hls_expected(stream: Stream, content_type: str) -> bool:
    if stream.protocol == StreamProtocol.HLS:
        return True
    if "mpegurl" in content_type.lower():
        return True
    return stream.url.lower().split("?")[0].endswith((".m3u8", ".m3u"))


def apply_rotation(streams: Sequence[Stream], offset: int, parts: int) -> list[Stream]:
    """Детерминированный stride-срез каталога для ротации проверок.

    Поток с индексом i попадает в срез при ``i % parts == offset``: за parts
    прогонов (offsets 0..parts-1) каталог покрывается ровно один раз, а каждый
    прогон равномерно представляет все источники, в отличие от contiguous-среза
    (issues #16, #17). Воспроизводимость: те же offset+parts — тот же срез.
    """
    if parts < 2:
        raise ValueError("rotate_parts must be >= 2")
    if not 0 <= offset < parts:
        raise ValueError(f"rotate_offset must be in [0, {parts})")
    return list(streams[offset::parts])


async def check_stream(
    stream: Stream,
    client: httpx.AsyncClient,
    settings: AppSettings,
    *,
    levels: Sequence[str] = DEFAULT_LEVELS,
    probe_location: str | None = None,
    country_code: str | None = None,
    ffprobe_bin: str | None = None,
    ffmpeg_bin: str | None = None,
    dvr_probe: bool | None = None,
) -> CheckResult:
    """Выполнить уровни проверки одного потока и собрать CheckResult."""
    result = CheckResult(
        stream_id=stream.stream_id,
        probe_location=resolve_probe_location(probe_location, settings),
        country_code=country_code,
    )
    level_set = set(levels)

    # Уровень 1 — быстрая HTTP-проверка.
    http_result = await fetch(
        client,
        stream.url,
        max_bytes=settings.check.head_bytes,
        max_redirects=settings.check.max_redirects,
    )

    code, message = classify_http(http_result)
    if (
        code in (CheckErrorCode.TIMEOUT, CheckErrorCode.TRANSPORT_ERROR)
        and settings.check.retry_transient
    ):
        # Транзиентная ошибка (issue #24): одна попытка повтора — разовый
        # сбой сети не портит uptime-статистику и не деградирует lifecycle.
        retry = await fetch(
            client,
            stream.url,
            max_bytes=settings.check.head_bytes,
            max_redirects=settings.check.max_redirects,
        )
        code, message = classify_http(retry)
        result.retried = True
        http_result = retry

    if (
        code == CheckErrorCode.HTTP_4XX
        and http_result.status in _UA_BLOCK_STATUSES
        and settings.check.ua_fallback
    ):
        # UA-fallback (issue #18): 401/403/444 часто означают блок по
        # User-Agent, а не мёртвый поток — повторяем с браузерным UA.
        # ~15% каталога отвечало 403 (измерено 2026-11-09).
        retry = await fetch(
            client,
            stream.url,
            max_bytes=settings.check.head_bytes,
            max_redirects=settings.check.max_redirects,
            extra_headers={"User-Agent": settings.check.browser_user_agent},
        )
        if classify_http(retry)[0] is None:
            http_result = retry
            result.ua_required = True
            code, message = None, None

    result.http_status = http_result.status or None
    result.dns_ok = http_result.dns_ok
    result.tls_ok = http_result.tls_ok
    result.startup_time_ms = http_result.elapsed_ms or None

    if code is not None:
        result.error_code = code
        result.error_message = redact_text(message or "")
        return result

    # Уровень 2 — HLS.
    if "hls" in level_set and _hls_expected(stream, http_result.headers.get("content-type", "")):
        # Для потоков с UA-fallback весь уровень ходит с браузерным UA (issue #18).
        ua_headers: dict[str, str] | None = None
        if result.ua_required:
            ua_headers = {"User-Agent": settings.check.browser_user_agent}
        hls = await check_hls(
            stream.url,
            client,
            max_bytes=max(settings.check.head_bytes * 4, 262144),
            segment_max_bytes=settings.check.head_bytes,
            max_redirects=settings.check.max_redirects,
            extra_headers=ua_headers,
            timeout_seconds=settings.check.hls_timeout_seconds,
            segment_timeout_seconds=settings.check.segment_timeout_seconds,
        )
        result.playlist_ok = hls.playlist_ok
        result.first_segment_ok = hls.first_segment_ok
        result.declared_height = hls.declared_height
        result.declared_bandwidth = hls.declared_bandwidth
        if hls.error_code is not None:
            result.error_code = hls.error_code
            result.error_message = redact_text(hls.error_message or "")
            return result

        # DVR-проба (issue #10): только после успешного базового чека,
        # не более двух запросов. Включается config'ом (check.dvr_probe);
        # dvr_probe=False из run_checks сужает скоуп до заданных потоков.
        probe_dvr_enabled = settings.check.dvr_probe if dvr_probe is None else dvr_probe
        if probe_dvr_enabled and hls.playlist_ok and hls.first_segment_ok and hls.media_url:
            dvr = await probe_dvr(
                hls.media_url,
                client,
                max_bytes=max(settings.check.head_bytes * 4, 262144),
                max_redirects=settings.check.max_redirects,
                extra_headers=ua_headers,
                timeout_seconds=settings.check.hls_timeout_seconds,
            )
            result.dvr = dvr.ok
            result.dvr_hours = dvr.hours if dvr.ok else None

    # Уровень 3 — медиапараметры.
    if "ffprobe" in level_set or "playback" in level_set:
        # Субпроцессы ffprobe/ffmpeg ходят по сети сами, мимо httpx-транспорта
        # с pinned-бэкендом (issue #23) — URL проверяется SSRF-защитой до
        # запуска. Редиректы ffmpeg не перепроверяются: принятый остаточный
        # риск (HTTP-уровень уже проверил цепочку редиректов; см. §8
        # docs/ARCHITECTURE.md).
        try:
            await validate_url(stream.url)
        except UrlGuardError as exc:
            result.error_code = exc.error_code
            result.error_message = redact_text(exc.reason or "ssrf blocked")
            return result

    if "ffprobe" in level_set:
        media = await probe_media(
            stream.url,
            ffprobe_bin=ffprobe_bin or os.environ.get("IPTV_FFPROBE_BIN", "ffprobe"),
            timeout_seconds=settings.check.ffprobe_timeout_seconds,
        )
        result.video_codec = media.video_codec
        result.audio_codec = media.audio_codec
        result.width = media.width
        result.height = media.height
        result.fps = media.fps
        result.bitrate_bps = media.bitrate_bps
        if media.error_code is not None:
            result.error_code = media.error_code
            result.error_message = redact_text(media.error_message or "")
            return result

    # Уровень 4 — ограниченное декодирование (используется выборочно).
    if "playback" in level_set:
        playback = await check_playback(
            stream.url,
            ffmpeg_bin=ffmpeg_bin or os.environ.get("IPTV_FFMPEG_BIN", "ffmpeg"),
            duration_seconds=settings.check.playback_duration_seconds,
        )
        result.duration_checked_seconds = playback.decoded_seconds
        if playback.error_code is not None:
            result.error_code = playback.error_code
            result.error_message = redact_text(playback.error_message or "")
            return result

    return result


async def run_checks(
    streams: Sequence[Stream],
    client: httpx.AsyncClient,
    settings: AppSettings,
    *,
    levels: Sequence[str] = DEFAULT_LEVELS,
    concurrency: int | None = None,
    probe_location: str | None = None,
    country_code: str | None = None,
    ffprobe_bin: str | None = None,
    ffmpeg_bin: str | None = None,
    progress: Callable[[int, CheckResult], None] | None = None,
    dvr_stream_ids: set[str] | None = None,
) -> list[CheckResult]:
    """Проверить потоки с ограничением параллелизма.

    Результаты возвращаются в порядке входного списка; прогресс-колбэк
    вызывается по завершении каждого потока. ``dvr_stream_ids`` ограничивает
    DVR-пробу (catchup) конкретными потоками (смягчение нагрузки на
    источники): None — для всех, если включён check.dvr_probe.
    """
    semaphore = asyncio.Semaphore(concurrency or settings.check.concurrency)
    completed = 0
    lock = asyncio.Lock()

    async def _one(stream: Stream) -> CheckResult:
        nonlocal completed
        async with semaphore:
            dvr_enabled = settings.check.dvr_probe and (
                dvr_stream_ids is None or stream.stream_id in dvr_stream_ids
            )
            result = await check_stream(
                stream,
                client,
                settings,
                levels=levels,
                probe_location=probe_location,
                country_code=country_code,
                ffprobe_bin=ffprobe_bin,
                ffmpeg_bin=ffmpeg_bin,
                dvr_probe=dvr_enabled,
            )
        async with lock:
            completed += 1
            if progress:
                progress(completed, result)
        return result

    outcomes = await asyncio.gather(*(_one(stream) for stream in streams), return_exceptions=True)

    # Необработанное исключение в check_stream не должно терять результаты
    # всего прогона: падение фиксируется как CheckResult с unknown-ошибкой
    # (issue #19). Сообщение редактируется — URL может содержать токены.
    results: list[CheckResult] = []
    for stream, outcome in zip(streams, outcomes, strict=True):
        if isinstance(outcome, BaseException):
            logger.warning(
                "check_stream failed for %s: %s",
                stream.stream_id,
                redact_text(f"{type(outcome).__name__}: {outcome}"),
            )
            outcome = CheckResult(
                stream_id=stream.stream_id,
                probe_location=resolve_probe_location(probe_location, settings),
                country_code=country_code,
                error_code=CheckErrorCode.UNKNOWN,
                error_message=redact_text(f"{type(outcome).__name__}: {outcome}"),
            )
        results.append(outcome)
    return results
