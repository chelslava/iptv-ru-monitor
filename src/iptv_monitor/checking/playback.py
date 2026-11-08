"""Ограниченный по времени проход FFmpeg (проверка запуска и декодирования).

Полное воспроизведение каждого потока на каждом цикле не требуется:
проход ограничен несколькими секундами и используется выборочно.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from ..domain.enums import CheckErrorCode
from ..infrastructure.logging import redact_text

logger = logging.getLogger(__name__)


@dataclass
class PlaybackOutcome:
    playback_ok: bool = False
    decoded_seconds: float | None = None
    error_code: CheckErrorCode | None = None
    error_message: str | None = None


async def check_playback(
    url: str,
    *,
    ffmpeg_bin: str = "ffmpeg",
    duration_seconds: float = 10.0,
    timeout_seconds: float | None = None,
) -> PlaybackOutcome:
    """Декодировать поток ограниченное время (ffmpeg -t ... -f null -)."""
    timeout = timeout_seconds or duration_seconds + 15.0
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-t",
        f"{duration_seconds:.0f}",
        "-i",
        url,
        "-f",
        "null",
        "-",
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, PermissionError):
        return PlaybackOutcome(
            error_code=CheckErrorCode.FFPROBE_UNAVAILABLE,
            error_message=f"ffmpeg binary not found: {ffmpeg_bin}",
        )

    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return PlaybackOutcome(
            error_code=CheckErrorCode.PLAYBACK_ERROR,
            error_message=f"playback exceeded {timeout}s",
        )

    if process.returncode != 0:
        message = redact_text(stderr.decode("utf-8", errors="replace").strip()[-300:])
        return PlaybackOutcome(error_code=CheckErrorCode.PLAYBACK_ERROR, error_message=message)

    return PlaybackOutcome(playback_ok=True, decoded_seconds=duration_seconds)
