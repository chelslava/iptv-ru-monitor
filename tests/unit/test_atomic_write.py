"""Атомарная запись файлов (issue #20): обрыв не оставляет урезанный файл."""

from __future__ import annotations

from pathlib import Path

import pytest

from iptv_monitor.domain.check_result import CheckResult
from iptv_monitor.generators.json_catalog import write_json
from iptv_monitor.history.retention import prune_storage
from iptv_monitor.infrastructure.atomic import atomic_write_text
from iptv_monitor.infrastructure.storage.jsonl import JsonlStorage


def test_atomic_write_text_replaces(tmp_path: Path) -> None:
    target = tmp_path / "out" / "file.txt"
    target.parent.mkdir(parents=True)
    target.write_text("old", encoding="utf-8")
    atomic_write_text(target, "new content")
    assert target.read_text(encoding="utf-8") == "new content"
    assert list(target.parent.glob("*.tmp")) == []


def test_atomic_write_creates_parent(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c.txt"
    atomic_write_text(target, "data")
    assert target.read_text(encoding="utf-8") == "data"


def test_interrupted_write_keeps_old_content(tmp_path: Path, monkeypatch) -> None:
    """Исключение посреди записи: целевой файл прежний, tmp не остаётся."""
    target = tmp_path / "data.json"
    write_json(target, {"version": 1})
    original = target.read_text(encoding="utf-8")

    import iptv_monitor.infrastructure.atomic as atomic_mod

    def broken_replace(src, dst):
        raise OSError("simulated crash mid-replace")

    monkeypatch.setattr(atomic_mod.os, "replace", broken_replace)
    with pytest.raises(OSError):
        atomic_write_text(target, "half written garbage")

    assert target.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob("*.tmp")) == []


def test_serialization_failure_keeps_file(tmp_path: Path, monkeypatch) -> None:
    """Несериализуемый payload: файл не трогается вовсе."""
    target = tmp_path / "data.json"
    write_json(target, {"ok": True})

    class Unserializable:
        pass

    with pytest.raises(TypeError):
        write_json(target, {"bad": Unserializable()})
    assert target.read_text(encoding="utf-8") == '{\n  "ok": true\n}'


def test_retention_prune_atomic(tmp_path: Path, monkeypatch) -> None:
    """Обрыв при перезаписи history не рвёт checks.jsonl."""
    storage = JsonlStorage(tmp_path / "checks.jsonl")
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    results = (
        [  # свежие — останутся в истории и попадут в перезапись
            CheckResult(stream_id=f"fresh{i}", probe_location="test", checked_at=now)
            for i in range(2)
        ]
        + [  # старые — отвалится retention'ом, перезапись будет запущена
            CheckResult(
                stream_id=f"old{i}", probe_location="test", checked_at=now - timedelta(days=31)
            )
            for i in range(3)
        ]
    )
    storage.append(results)
    before = storage.path.read_text(encoding="utf-8")

    def broken_dump(self):
        raise RuntimeError("simulated crash during rewrite")

    monkeypatch.setattr(CheckResult, "model_dump_json", broken_dump)
    with pytest.raises(RuntimeError):
        prune_storage(storage, history_days=30, max_results_per_stream=200)

    assert storage.path.read_text(encoding="utf-8") == before
    assert list(tmp_path.glob("*.tmp")) == []
