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
    # Заявленные параметры выбранного варианта (issue #24): заполняются
    # из master-плейлиста и работают без ffprobe.
    declared_height: int | None = None
    declared_bandwidth: int | None = None
    error_code: CheckErrorCode | None = None
    error_message: str | None = None


def parse_variant_height(resolution: str | None) -> int | None:
    """Высота из RESOLUTION '1280x720' -> 720 (issue #24)."""
    if not resolution or "x" not in resolution:
        return None
    try:
        return int(resolution.rsplit("x", 1)[1])
    except ValueError:
        return None


def select_variant(variants: list[HlsVariant]) -> HlsVariant:
    """Выбрать вариант проверки: минимальный bandwidth (issue #24).

    Низкий bitrate с наибольшей вероятностью отдаёт playable-поток и
    подтверждает работоспособность; раньше брался variants[0] вслепую.
    """
    return min(variants, key=lambda v: v.bandwidth if v.bandwidth is not None else 0)


def looks_like_media_bytes(body: bytes) -> bool:
    """Похоже ли начало сегмента на медиаданные (issue #24).

    MPEG-TS (0x47), fMP4 ('ftyp'), ADTS AAC (0xFF 0xF1/0xF9), MP3 (ID3 /
    0xFF 0xFB), WebM (EBML). Отсекает HTML-страницы ошибок с кодом 200 и
    мусор от серверов, игнорирующих Range.
    """
    if len(body) < 4:
        return False
    if body[0] == 0x47:  # MPEG-TS
        return True
    if body[4:8] == b"ftyp" or body.startswith(b"ftyp"):  # fMP4/MP4
        return True
    if body[:2] == b"\xff\xf1" or body[:2] == b"\xff\xf9":  # ADTS AAC
        return True
    if body[:3] == b"ID3" or body[:2] == b"\xff\xfb":  # MP3
        return True
    if body.startswith(b"\x1aE\xdf\xa3"):  # EBML (WebM/Matroska)
        return True
    return False


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
    extra_headers: dict[str, str] | None = None,
) -> DvrOutcome:
    """DVR-проба Flussonic: не более двух запросов после успешного базового чека.

    Варианты по порядку: ``?utc=<epoch>`` на media URL, затем
    ``timeshift_abs-{utc}.m3u8`` в той же директории. Успех = 2xx и
    валидный media playlist с сегментами за час назад (DVR >= 1 ч).
    ``extra_headers`` (например, браузерный User-Agent, issue #18)
    прокидываются в каждый запрос.
    """
    utc = int(time.time()) - hours_ago * 3600
    separator = "&" if "?" in media_url else "?"
    candidates = [
        f"{media_url}{separator}utc={utc}",
        flussonic_timeshift_url(media_url, utc),
    ]
    for url in candidates:
        response = await fetch(
            client,
            url,
            max_bytes=max_bytes,
            max_redirects=max_redirects,
            extra_headers=extra_headers,
        )
        if response.error_code or response.status >= 400:
            continue
        text = response.body.decode("utf-8", errors="replace")
        if not (
            looks_like_playlist(text) and parse_media_playlist(text, response.final_url or url)
        ):
            continue
        # Честность пробы (issue #24): серверы, игнорирующие utc, отдают
        # live-окно — сравниваем с плейлистом без utc; совпал — архива нет.
        live = await fetch(
            client,
            media_url,
            max_bytes=max_bytes,
            max_redirects=max_redirects,
            extra_headers=extra_headers,
        )
        if not live.error_code and live.status < 400:
            live_text = live.body.decode("utf-8", errors="replace")
            if live_text.strip() == text.strip():
                return DvrOutcome(ok=False)
        return DvrOutcome(ok=True, hours=hours_ago)
    return DvrOutcome(ok=False)


async def check_hls(
    url: str,
    client: httpx.AsyncClient,
    *,
    max_bytes: int = 262144,
    segment_max_bytes: int = 65536,
    max_redirects: int = 5,
    extra_headers: dict[str, str] | None = None,
) -> HlsOutcome:
    """Проверить HLS: playlist, варианты качества, первый сегмент.

    Ошибки и истечение токенов проявляются на этапе сегмента — поэтому
    получение сегмента обязательно для подтверждения работоспособности.
    ``extra_headers`` (например, браузерный User-Agent, issue #18)
    применяются ко всем запросам уровня.
    """
    outcome = HlsOutcome()

    response = await fetch(
        client,
        url,
        max_bytes=max_bytes,
        max_redirects=max_redirects,
        extra_headers=extra_headers,
    )
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
        # Выбор варианта и заявленные параметры (issue #24): минимальный
        # bandwidth, высота из RESOLUTION — без ffprobe.
        variant = select_variant(outcome.variants)
        outcome.declared_bandwidth = variant.bandwidth
        outcome.declared_height = parse_variant_height(variant.resolution)
        media_url = variant.uri
    else:
        media_url = base

    # Получаем media playlist (либо сам URL — media).
    media_response = await fetch(
        client,
        media_url,
        max_bytes=max_bytes,
        max_redirects=max_redirects,
        extra_headers=extra_headers,
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
        # Валидный плейлист без сегментов (EVENT только начался, VOD
        # закончился) — не успех HLS: смотреть нечего (issue #24).
        outcome.error_code = CheckErrorCode.PLAYLIST_EMPTY
        outcome.error_message = "playlist has no segments"
        return outcome

    segment_url = segments[0]
    outcome.segment_url = segment_url
    segment_headers = dict(extra_headers) if extra_headers else {}
    segment_headers["Range"] = f"bytes=0-{segment_max_bytes - 1}"
    segment_response = await fetch(
        client,
        segment_url,
        max_bytes=segment_max_bytes,
        max_redirects=max_redirects,
        extra_headers=segment_headers,
    )
    if segment_response.error_code:
        outcome.error_code = segment_response.error_code
        outcome.error_message = f"segment: {segment_response.error_message}"
        return outcome
    if segment_response.status >= 400:
        outcome.error_code = CheckErrorCode.SEGMENT_ERROR
        outcome.error_message = f"http {segment_response.status} for first segment"
        return outcome

    # Sniffing начала сегмента (issue #24): сервер, игнорирующий Range,
    # может отдать HTML-страницу с 200 — по magic bytes отсекаем мусор.
    if not looks_like_media_bytes(segment_response.body):
        outcome.error_code = CheckErrorCode.SEGMENT_ERROR
        outcome.error_message = "segment is not media data"
        return outcome

    outcome.first_segment_ok = True
    return outcome
