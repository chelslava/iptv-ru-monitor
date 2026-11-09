"""Атомарная запись файлов: tmp-файл в том же каталоге + os.replace (issue #20).

Обрыв процесса посреди записи больше не оставляет урезанный
channels.json / checks.jsonl / плейлист: целевой файл либо прежний,
либо новый целиком. tmp-файл создаётся в каталоге цели (та же файловая
система — os.replace атомарен), при ошибке удаляется.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO


def _atomic_write(path: Path, writer: Callable[[BinaryIO], object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            writer(fh)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Записать текстовый файл атомарно."""
    _atomic_write(path, lambda fh: fh.write(text.encode(encoding)))


def atomic_write_json(path: Path, payload: object, *, indent: int = 2) -> None:
    """Записать JSON-файл атомарно (ensure_ascii=False, форматирование как раньше)."""
    data = json.dumps(payload, ensure_ascii=False, indent=indent).encode("utf-8")
    _atomic_write(path, lambda fh: fh.write(data))
