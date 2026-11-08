"""Хранилища истории проверок."""

from ...settings import AppSettings
from .base import CheckStorage
from .jsonl import JsonlStorage
from .sqlite import SqliteStorage

__all__ = ["CheckStorage", "JsonlStorage", "SqliteStorage", "create_storage"]


def create_storage(settings: AppSettings) -> CheckStorage:
    """Создать хранилище по конфигурации (backend: jsonl | sqlite)."""
    backend = settings.storage.backend.lower()
    if backend == "jsonl":
        return JsonlStorage(settings.storage.jsonl_path)
    if backend == "sqlite":
        return SqliteStorage(settings.storage.sqlite_path)
    raise ValueError(f"unknown storage backend: {backend!r}")
