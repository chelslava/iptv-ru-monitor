"""Тесты доменных моделей и хранилищ."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from iptv_monitor.domain.channel import Channel
from iptv_monitor.domain.check_result import CheckResult
from iptv_monitor.domain.stream import detect_protocol, make_stream_id
from iptv_monitor.infrastructure.storage import JsonlStorage, SqliteStorage
from iptv_monitor.settings import AppSettings, load_settings


def test_check_result_json_roundtrip(make_result) -> None:
    result = make_result(video_codec="h264", audio_codec="aac", fps=25.0)
    restored = CheckResult.model_validate_json(result.model_dump_json())
    assert restored == result


def test_check_result_success_semantics(make_result) -> None:
    assert make_result().is_success()
    assert not make_result(error_code="timeout", error_message="t").is_success()


def test_stream_id_deterministic() -> None:
    assert make_stream_id("https://x.example/a.m3u8") == make_stream_id("https://x.example/a.m3u8")
    assert make_stream_id("https://x.example/a.m3u8") != make_stream_id("https://x.example/b.m3u8")


def test_detect_protocol() -> None:
    assert detect_protocol("https://x/a.m3u8").value == "hls"
    assert detect_protocol("https://x/live.m3u8?token=1").value == "hls"
    assert detect_protocol("https://x/stream.mpd").value == "dash"
    assert detect_protocol("https://x/live.ts").value == "http"


def test_channel_country_validation() -> None:
    with pytest.raises(ValueError):
        Channel(channel_id="x", name="X", country="RUS")


def _storage_results(make_result) -> tuple[list[CheckResult], datetime]:
    """Детерминированная история: поток a — 5 проверок (5..1 ч назад), b — 3 (90/50/10 мин)."""
    now = datetime.now(UTC)
    results = [
        make_result(stream_id="a", checked_at=now - timedelta(hours=h)) for h in (6, 5, 4, 3, 2)
    ]
    results += [
        make_result(stream_id="b", checked_at=now - timedelta(minutes=m)) for m in (90, 50, 10)
    ]
    return results, now


def test_jsonl_storage_roundtrip(tmp_path, make_result) -> None:
    storage = JsonlStorage(tmp_path / "checks.jsonl")
    results, now = _storage_results(make_result)
    storage.append(results)

    loaded = storage.load()
    assert len(loaded) == 8
    only_a = storage.load(stream_id="a")
    assert len(only_a) == 5
    assert all(r.stream_id == "a" for r in only_a)
    limited = storage.load(limit=2)
    assert [r.stream_id for r in limited] == ["b", "b"]  # последние по времени
    since = now - timedelta(minutes=60)
    recent = storage.load(since=since)
    assert [r.stream_id for r in recent] == ["b", "b"]  # 50 и 10 минут назад


def test_jsonl_storage_skips_malformed_lines(tmp_path, make_result) -> None:
    path = tmp_path / "checks.jsonl"
    storage = JsonlStorage(path)
    storage.append([make_result()])
    with path.open("a", encoding="utf-8") as fh:
        fh.write("not-json\n")
        fh.write('{"unexpected": true}\n')
    storage2 = JsonlStorage(path)
    assert len(storage2.load()) == 1


def test_sqlite_storage_roundtrip(tmp_path, make_result) -> None:
    storage = SqliteStorage(tmp_path / "history.sqlite")
    results, now = _storage_results(make_result)
    storage.append(results)

    assert len(storage.load()) == 8
    assert len(storage.load(stream_id="b")) == 3
    since = now - timedelta(minutes=60)
    assert [r.stream_id for r in storage.load(since=since)] == ["b", "b"]
    storage.close()


def test_load_settings_defaults(tmp_path, monkeypatch) -> None:
    for var in ("IPTV_CONFIG_DIR", "IPTV_DATA_DIR", "IPTV_DIST_DIR", "IPTV_PROBE_LOCATION"):
        monkeypatch.delenv(var, raising=False)
    settings = load_settings(tmp_path)  # пустой каталог конфигурации
    assert isinstance(settings, AppSettings)
    assert settings.paths.data_dir == Path("data")
    assert settings.check.concurrency > 0


def test_load_settings_env_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("IPTV_PROBE_LOCATION", "ru-vds")
    monkeypatch.setenv("IPTV_DATA_DIR", str(tmp_path / "custom-data"))
    settings = load_settings(tmp_path)
    assert settings.probe_location == "ru-vds"
    assert settings.paths.data_dir == tmp_path / "custom-data"
