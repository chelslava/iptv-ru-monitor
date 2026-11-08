"""Тесты разбора вывода FFprobe (без запуска бинарника)."""

from __future__ import annotations

import json

from iptv_monitor.checking.ffprobe import _parse_ffprobe_json, parse_frame_rate
from iptv_monitor.domain.enums import CheckErrorCode

PAYLOAD = json.dumps(
    {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "50/1",
                "bit_rate": "4500000",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"bit_rate": "4600000"},
    }
)


def test_parse_frame_rate() -> None:
    assert parse_frame_rate("50/1") == 50.0
    assert parse_frame_rate("30000/1001") == 29.97
    assert parse_frame_rate("25") == 25.0
    assert parse_frame_rate("0/0") is None
    assert parse_frame_rate(None) is None


def test_parse_full_payload() -> None:
    outcome = _parse_ffprobe_json(PAYLOAD)
    assert outcome.error_code is None
    assert outcome.video_codec == "h264"
    assert outcome.audio_codec == "aac"
    assert (outcome.width, outcome.height) == (1920, 1080)
    assert outcome.fps == 50.0
    assert outcome.bitrate_bps == 4600000


def test_invalid_json_is_error() -> None:
    outcome = _parse_ffprobe_json("<not json>")
    assert outcome.error_code == CheckErrorCode.FFPROBE_ERROR


def test_no_streams_is_error() -> None:
    outcome = _parse_ffprobe_json(json.dumps({"streams": [], "format": {}}))
    assert outcome.error_code == CheckErrorCode.FFPROBE_ERROR
    assert "no audio or video" in (outcome.error_message or "")
