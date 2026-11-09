"""Перечисления доменной области."""

from __future__ import annotations

from enum import StrEnum


class StreamProtocol(StrEnum):
    """Протокол потока."""

    HLS = "hls"
    HTTP = "http"  # прямая ссылка (MPEG-TS и т. п.)
    DASH = "dash"
    UNKNOWN = "unknown"


class PublicationStatus(StrEnum):
    """Допуск потока к публикации."""

    PENDING = "pending"
    ALLOWED = "allowed"
    REJECTED = "rejected"


class PublicPolicy(StrEnum):
    """Политика публикации потоков источника."""

    ALLOW = "allow"
    REVIEW = "review"
    DENY = "deny"


class Category(StrEnum):
    """Категория канала."""

    GENERAL = "general"
    NEWS = "news"
    KIDS = "kids"
    SPORTS = "sports"
    MOVIES = "movies"
    MUSIC = "music"
    EDUCATION = "education"
    ENTERTAINMENT = "entertainment"
    RELIGIOUS = "religious"
    WEATHER = "weather"


class QualityLevel(StrEnum):
    """Уровень качества потока по итогам скоринга."""

    EXCELLENT = "excellent"
    GOOD = "good"
    UNSTABLE = "unstable"
    FAILED = "failed"
    INSUFFICIENT_DATA = "insufficient_data"


class MatchMethod(StrEnum):
    """Способ сопоставления канала с EPG/логотипом."""

    TVG_ID = "tvg_id"
    ALIAS = "alias"
    NORMALIZED_NAME = "normalized_name"
    BRIDGE = "bridge"  # имя найдено через iptv-org/database (issue #5)
    FUZZY = "fuzzy"  # зарезервировано; не перезаписывает ручные совпадения
    MANUAL = "manual"


class CheckErrorCode(StrEnum):
    """Классификация ошибок проверки потока."""

    SSRF_BLOCKED = "ssrf_blocked"
    UNSUPPORTED_SCHEME = "unsupported_scheme"
    REDIRECT_LIMIT = "redirect_limit"
    REDIRECT_INVALID = "redirect_invalid"  # редирект без Location (issue #19)
    DNS_ERROR = "dns_error"
    TLS_ERROR = "tls_error"
    HTTP_4XX = "http_4xx"
    HTTP_5XX = "http_5xx"
    TRANSPORT_ERROR = "transport_error"
    TIMEOUT = "timeout"
    INVALID_CONTENT = "invalid_content"
    HLS_INVALID = "hls_invalid"
    HLS_VARIANT_UNAVAILABLE = "hls_variant_unavailable"
    PLAYLIST_EMPTY = "playlist_empty"  # валидный плейлист без сегментов (issue #24)
    SEGMENT_ERROR = "segment_error"
    FFPROBE_UNAVAILABLE = "ffprobe_unavailable"
    FFPROBE_TIMEOUT = "ffprobe_timeout"
    FFPROBE_ERROR = "ffprobe_error"
    PLAYBACK_ERROR = "playback_error"
    UNKNOWN = "unknown"
