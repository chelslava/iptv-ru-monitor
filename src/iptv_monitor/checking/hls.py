"""Уровень 2 — проверка HLS: master/media playlist, первый сегмент, DVR-проба."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from ..domain.enums import CheckErrorCode
from ..infrastructure.http_client import fetch


@dataclass
class HlsVariant:
    uri: str
    bandwidth: int | None = None
    resolution: str | None = None


@dataclass
class HlsOutcome:
    playlist_ok: bool = False
    is_master: bool = False
    variants: list[HlsVariant] = field(default_factory=list)
    media_url: str | None = None
    first_segment_ok: bool | None = None
    segment_url: str | None = None
    error_code: CheckErrorCode | None = None
    error_message: str | None = None


def parse_master_playlist(text: str, base_url: str) -> list[HlsVariant]:
    """Разобрать master playlist: #EXT-X-STREAM-INF + URI следующей строкой."""
    variants: list[HlsVariant] = []
    pending_attrs: dict[str, str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("#EXT-X-STREAM-INF"):
            attrs: dict[str, str] = {}
            # BANDWIDTH=123456,RESOLUTION=1280x720
            for part in line.split(":", 1)[1].split(","):
                if "=" in part:
                    key, _, value = part.partition("=")
                    attrs[key.strip().upper()] = value.strip().strip('"')
            pending_attrs = attrs
        elif line and not line.startswith("#") and pending_attrs is not None:
            bandwidth = pending_attrs.get("BANDWIDTH")
            variants.append(
                HlsVariant(
                    uri=urljoin(base_url, line),
                    bandwidth=int(bandwidth) if bandwidth and bandwidth.isdigit() else None,
                    resolution=pending_attrs.get("RESOLUTION"),
                )
            )
            pending_attrs = None
    return variants


def parse_media_playlist(text: str, base_url: str) -> list[str]:
    """Вернуть абсолютные URL сегментов в порядке объявления."""
    segments: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            segments.append(urljoin(base_url, line))
    return segments


def looks_like_playlist(text: str) -> bool:
    return text.lstrip().startswith("#EXTM3U")


def flussonic_timeshift_url(media_url: str, utc: int) -> str:
    """Flussonic DVR-URL: последний сегмент пути -> timeshift_abs-{utc}.m3u8."""
    parts = urlsplit(media_url)
    directory = parts.path.rsplit("/", 1)[0]
    return urlunsplit(parts._replace(path=f"{directory}/timeshift_abs-{utc}.m3u8"))


def flussonic_catchup_source(url: str) -> str:
    """Шаблон catchup-source для TiviMate (плейсхолдеры {utc}/{duration}).

    Строится от stream URL, а не от media URL: stream URL уже прошёл
    проверку секретов при публикации; media URL может нести токены.
    """
    if "?" in url:
        return f"{url}&utc={{utc}}&duration={{duration}}"
    return flussonic_timeshift_url(url, 0).replace(
        "timeshift_abs-0.m3u8", "timeshift_abs-{utc}.m3u8"
    )


@dataclass
class DvrOutcome:
    """Результат DVR-пробы (catchup/архив, issue #10)."""

    ok: bool = False
    hours: int | None = None


async def probe_dvr(
    media_url: str,
    client: httpx.AsyncClient,
    *,
    max_bytes: int = 262144,
    max_redirects: int = 5,
    hours_ago: int = 1,
) -> DvrOutcome:
    """DVR-проба Flussonic: не более двух запросов после успешного базового чека.

    Варианты по порядку: ``?utc=<epoch>`` на media URL, затем
    ``timeshift_abs-{utc}.m3u8`` в той же директории. Успех = 2xx и
    валидный media playlist с сегментами за час назад (DVR >= 1 ч).
    """
    utc = int(time.time()) - hours_ago * 3600
    separator = "&" if "?" in media_url else "?"
    candidates = [
        f"{media_url}{separator}utc={utc}",
        flussonic_timeshift_url(media_url, utc),
    ]
    for url in candidates:
        response = await fetch(client, url, max_bytes=max_bytes, max_redirects=max_redirects)
        if response.error_code or response.status >= 400:
            continue
        text = response.body.decode("utf-8", errors="replace")
        if looks_like_playlist(text) and parse_media_playlist(text, response.final_url or url):
            return DvrOutcome(ok=True, hours=hours_ago)
    return DvrOutcome(ok=False)


async def check_hls(
    url: str,
    client: httpx.AsyncClient,
    *,
    max_bytes: int = 262144,
    segment_max_bytes: int = 65536,
    max_redirects: int = 5,
) -> HlsOutcome:
    """Проверить HLS: playlist, варианты качества, первый сегмент.

    Ошибки и истечение токенов проявляются на этапе сегмента — поэтому
    получение сегмента обязательно для подтверждения работоспособности.
    """
    outcome = HlsOutcome()

    response = await fetch(client, url, max_bytes=max_bytes, max_redirects=max_redirects)
    if response.error_code:
        outcome.error_code = response.error_code
        outcome.error_message = response.error_message
        return outcome
    if response.status >= 400:
        outcome.error_code = (
            CheckErrorCode.HTTP_5XX if response.status >= 500 else CheckErrorCode.HTTP_4XX
        )
        outcome.error_message = f"http {response.status}"
        return outcome

    text = response.body.decode("utf-8", errors="replace")
    if not looks_like_playlist(text):
        outcome.error_code = CheckErrorCode.HLS_INVALID
        outcome.error_message = "response is not an M3U8 playlist"
        return outcome

    base = response.final_url or url
    if "#EXT-X-STREAM-INF" in text:
        outcome.is_master = True
        outcome.variants = parse_master_playlist(text, base)
        if not outcome.variants:
            outcome.error_code = CheckErrorCode.HLS_VARIANT_UNAVAILABLE
            outcome.error_message = "master playlist has no variants"
            return outcome
        media_url = outcome.variants[0].uri
    else:
        media_url = base

    # Получаем media playlist (либо сам URL — media).
    media_response = await fetch(
        client, media_url, max_bytes=max_bytes, max_redirects=max_redirects
    )
    if media_response.error_code:
        outcome.error_code = media_response.error_code
        outcome.error_message = media_response.error_message
        return outcome
    if media_response.status >= 400:
        outcome.error_code = (
            CheckErrorCode.HTTP_5XX if media_response.status >= 500 else CheckErrorCode.HTTP_4XX
        )
        outcome.error_message = f"http {media_response.status} for media playlist"
        return outcome

    media_text = media_response.body.decode("utf-8", errors="replace")
    media_base = media_response.final_url or media_url
    if not looks_like_playlist(media_text):
        outcome.error_code = CheckErrorCode.HLS_INVALID
        outcome.error_message = "media playlist is not valid M3U8"
        return outcome

    outcome.playlist_ok = True
    outcome.media_url = media_url

    segments = parse_media_playlist(media_text, media_base)
    if not segments:
        # Плейлист валиден, но сегментов нет (например, VOD закончился).
        return outcome

    segment_url = segments[0]
    outcome.segment_url = segment_url
    segment_response = await fetch(
        client,
        segment_url,
        max_bytes=segment_max_bytes,
        max_redirects=max_redirects,
        extra_headers={"Range": f"bytes=0-{segment_max_bytes - 1}"},
    )
    if segment_response.error_code:
        outcome.error_code = segment_response.error_code
        outcome.error_message = f"segment: {segment_response.error_message}"
        return outcome
    if segment_response.status >= 400:
        outcome.error_code = CheckErrorCode.SEGMENT_ERROR
        outcome.error_message = f"http {segment_response.status} for first segment"
        return outcome

    outcome.first_segment_ok = True
    return outcome
