"""Конфигурация источника данных (описывается в config/sources.yaml)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, field_validator

from .enums import PublicPolicy


class SourceConfig(BaseModel):
    """Источник IPTV-потоков (см. docs/SOURCE_POLICY.md)."""

    id: str
    adapter: str  # iptv_org | free_tv | custom_m3u | ...
    enabled: bool = True
    country: str | None = None
    public_policy: PublicPolicy = PublicPolicy.REVIEW
    url: str | None = None
    path: Path | None = None
    refresh_hours: int = 24

    @field_validator("country")
    @classmethod
    def _validate_country(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        if len(value) != 2 or not value.isalpha():
            raise ValueError(f"country must be ISO 3166-1 alpha-2, got {value!r}")
        return value

    @property
    def location(self) -> str:
        """Откуда забирать данные: URL или локальный путь."""
        if self.url:
            return self.url
        if self.path:
            return str(self.path)
        raise ValueError(f"source {self.id!r} has neither url nor path")
