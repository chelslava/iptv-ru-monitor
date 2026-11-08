"""Поток — конкретный URL вещания, привязанный к каналу и источнику."""

from __future__ import annotations

import hashlib
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator

from .enums import PublicationStatus, StreamProtocol


def make_stream_id(url: str) -> str:
    """Стабильный детерминированный ID потока (первые 16 hex sha256 URL)."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def detect_protocol(url: str) -> StreamProtocol:
    """Первичное определение протокола по расширению.

    Уточняется по Content-Type во время проверки.
    """
    path = urlparse(url).path.lower()
    if path.endswith((".m3u8", ".m3u")):
        return StreamProtocol.HLS
    if path.endswith(".mpd"):
        return StreamProtocol.DASH
    return StreamProtocol.HTTP


class Stream(BaseModel):
    """Поток канала (см. docs/DATA_MODEL.md).

    Секретные URL и адреса с временными токенами не допускаются к публикации:
    см. filtering/publication_policy.py.
    """

    stream_id: str
    channel_id: str
    url: str
    protocol: StreamProtocol
    source_id: str
    declared_quality: str | None = None
    enabled: bool = True
    publication_status: PublicationStatus = PublicationStatus.PENDING

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"stream url must be http(s), got {value!r}")
        return value
