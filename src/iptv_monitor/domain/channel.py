"""Канал — каноническая сущность, отделённая от конкретных потоков."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from .enums import Category

_COUNTRY_RE = re.compile(r"^[A-Za-z]{2}$")


class Channel(BaseModel):
    """Нормализованный телеканал (см. docs/DATA_MODEL.md)."""

    channel_id: str
    name: str
    alt_names: list[str] = Field(default_factory=list)
    country: str  # ISO 3166-1 alpha-2
    languages: list[str] = Field(default_factory=list)
    category: Category = Category.GENERAL
    tvg_id: str | None = None
    logo_url: str | None = None
    is_public: bool = False
    metadata_source: str | None = None

    @field_validator("country")
    @classmethod
    def _validate_country(cls, value: str) -> str:
        value = value.strip().upper()
        if not _COUNTRY_RE.match(value):
            raise ValueError(f"country must be ISO 3166-1 alpha-2, got {value!r}")
        return value
