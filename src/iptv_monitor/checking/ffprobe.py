"""Уровень 3 — медиапроверка через FFprobe.

Определяются наличие видео и аудио, кодеки, разрешение, FPS и оценка
битрейта. Запуск ограничен по времени и размеру анализа.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
from dataclasses import dataclass

from ..domain.enums import CheckErrorCode
from ..infrastructure.logging import redact_text

logger = logging.getLogger(__name__)


@dataclass
class MediaOutcome:
    video_codec: str | None = None
    audio_codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    bitrate_bps: int | None = None
    error_code: CheckErrorCode | None = None
    error_message: str | None = None


def parse_frame_rate(value: str | None) -> float | None:
    """Разобрать частоту кадров вида '50/1', '30000/1001' или '25'."""
    if not value or "/" not in value:
        return float(value) if value else None
    num, _, den = value.partition("/")
    try:
        numerator, denominator = float(num), float(den)
    except ValueError:
        return None
    if denominator == 0 or numerator == 0:
        return None
    return round(numerator / denominator, 3)


def _parse_ffprobe_json(payload: str) -> MediaOutcome:
    outcome = MediaOutcome()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        outcome.error_code = CheckErrorCode.FFPROBE_ERROR
        outcome.error_message = "invalid ffprobe json output"
        return outcome

    for stream in data.get("streams", []):
        codec_type = stream.get("codec_type")
        if codec_type == "video" and outcome.video_codec is None:
            outcome.video_codec = stream.get("codec_name")
            outcome.width = stream.get("width")
            outcome.height = stream.get("height")
            outcome.fps = parse_frame_rate(stream.get("avg_frame_rate"))
        elif codec_type == "audio" and outcome.audio_codec is None:
            outcome.audio_codec = stream.get("codec_name")

    fmt = data.get("format", {})
    bitrate = fmt.get("bit_rate") or next(
        (s.get("bit_rate") for s in data.get("streams", []) if s.get("bit_rate")), None
    )
    try:
        outcome.bitrate_bps = int(bitrate) if bitrate else None
    except (TypeError, ValueError):
        outcome.bitrate_bps = None
    if outcome.video_codec is None and outcome.audio_codec is None:
        outcome.error_code = CheckErrorCode.FFPROBE_ERROR
        outcome.error_message = "no audio or video streams found"
    return outcome


async def probe_media(
    url: str,
    *,
    ffprobe_bin: str = "ffprobe",
    timeout_seconds: float = 30.0,
) -> MediaOutcome:
    """Запустить FFprobe для потока с тайм-аутом."""
    cmd = [
        ffprobe_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        "-analyzeduration",
        "5000000",
        "-probesize",
        "5000000",
        "-i",
        url,
    ]
    logger.debug("ffprobe: %s", " ".join(shlex.quote(part) for part in cmd[:-2]))

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, PermissionError):
        return MediaOutcome(
            error_code=CheckErrorCode.FFPROBE_UNAVAILABLE,
            error_message=f"ffprobe binary not found: {ffprobe_bin}",
        )

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout_seconds)
    except TimeoutError:
        process.kill()
        await process.wait()
        return MediaOutcome(
            error_code=CheckErrorCode.FFPROBE_TIMEOUT,
            error_message=f"ffprobe exceeded {timeout_seconds}s",
        )

    if process.returncode != 0:
        message = redact_text(stderr.decode("utf-8", errors="replace").strip()[-300:])
        return MediaOutcome(error_code=CheckErrorCode.FFPROBE_ERROR, error_message=message)

    return _parse_ffprobe_json(stdout.decode("utf-8", errors="replace"))
