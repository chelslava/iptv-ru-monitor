"""CheckResult — одна проверка одного потока из одной точки наблюдения."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from .. import __version__
from .enums import CheckErrorCode


def now_utc() -> datetime:
    """Текущий момент времени в UTC (timezone-aware)."""
    return datetime.now(UTC)


class CheckResult(BaseModel):
    """Результат проверки потока (см. docs/DATA_MODEL.md, раздел CheckResult)."""

    stream_id: str
    checked_at: datetime = Field(default_factory=now_utc)
    probe_location: str  # github-runner | ru-vds | local | ...
    country_code: str | None = None

    # Уровень 1 — HTTP.
    http_status: int | None = None
    dns_ok: bool | None = None
    tls_ok: bool | None = None

    # Уровень 2 — HLS.
    playlist_ok: bool | None = None
    first_segment_ok: bool | None = None

    startup_time_ms: int | None = None

    # Уровень 3 — медиапараметры.
    video_codec: str | None = None
    audio_codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    bitrate_bps: int | None = None
    duration_checked_seconds: float | None = None

    error_code: CheckErrorCode | None = None
    error_message: str | None = None

    # DVR/catchup (issue #10): заполняется DVR-пробой Flussonic при
    # check.dvr_probe=true. dvr_hours — подтверждённая глубина архива.
    dvr: bool | None = None
    dvr_hours: int | None = None

    check_version: str = __version__

    def is_success(self) -> bool:
        """Проверка считается успешной, если нет классифицированной ошибки."""
        return self.error_code is None
