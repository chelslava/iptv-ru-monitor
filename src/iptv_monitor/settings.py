"""Загрузка конфигурации проекта (config/*.yaml) и переопределений окружением.

Все загрузчики конфигурации собраны здесь, чтобы остальные модули оставались
чистыми функциями над моделями и не зависели от файловой системы.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .domain.enums import Category, PublicPolicy
from .domain.source import SourceConfig

_DEFAULT_CONFIG_DIR = Path("config")


def read_yaml(path: Path) -> dict[str, Any]:
    """Прочитать YAML-файл; отсутствующий файл — пустая конфигурация."""
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


# --- app.yaml ---------------------------------------------------------------


class AppConfig(BaseModel):
    name: str = "iptv-ru-monitor"
    log_level: str = "INFO"


class PathsConfig(BaseModel):
    data_dir: Path = Path("data")
    dist_dir: Path = Path("dist")


class CheckSettings(BaseModel):
    concurrency: int = 8
    max_redirects: int = 5
    http_timeout_seconds: float = 10.0
    hls_timeout_seconds: float = 15.0
    segment_timeout_seconds: float = 10.0
    head_bytes: int = 65536
    ffprobe_timeout_seconds: float = 30.0
    playback_duration_seconds: float = 10.0
    user_agent: str = "iptv-ru-monitor/0.1"
    # DVR-проба Flussonic (issue #10): catchup-атрибуты в плейлисте.
    # dvr_probe_scope: «approved» — только подтверждённые потоки
    # (два запроса на поток лишь для ~100 штук), «all» — все прошедшие HLS.
    dvr_probe: bool = False
    dvr_probe_scope: str = "all"


class StorageSettings(BaseModel):
    backend: str = "jsonl"  # jsonl | sqlite
    jsonl_path: Path = Path("data/state/checks.jsonl")
    sqlite_path: Path = Path("data/state/history.sqlite")


class RetentionSettings(BaseModel):
    history_days: int = 30  # окно артефактов проверок и probe/ru (issue #13)
    max_results_per_stream: int = 200


class LifecycleSettings(BaseModel):
    """Автодеградация мёртвых потоков (issue #8).

    N провалов подряд (по всем точкам) — stale (публикуется с пометкой
    в отчёте), 2N — автодeny (исключается из плейлиста). Один успех
    сбрасывает счётчик.
    """

    stale_consecutive_failures: int = 6
    deny_consecutive_failures: int = 12


class ScoringSettings(BaseModel):
    min_checks: int = 5


class GeoSettings(BaseModel):
    ip_info_url: str | None = None


class AppSettings(BaseModel):
    """Полная конфигурация приложения."""

    app: AppConfig = Field(default_factory=AppConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    probe_location: str = "local"
    check: CheckSettings = Field(default_factory=CheckSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    retention: RetentionSettings = Field(default_factory=RetentionSettings)
    lifecycle: LifecycleSettings = Field(default_factory=LifecycleSettings)
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)
    geo: GeoSettings = Field(default_factory=GeoSettings)
    config_dir: Path = _DEFAULT_CONFIG_DIR

    @property
    def input_dir(self) -> Path:
        return self.paths.data_dir / "input"

    @property
    def cache_dir(self) -> Path:
        return self.paths.data_dir / "cache"

    @property
    def state_dir(self) -> Path:
        return self.paths.data_dir / "state"

    @property
    def dist_dir(self) -> Path:
        return self.paths.dist_dir


def load_settings(config_dir: Path | None = None, **overrides: Any) -> AppSettings:
    """Загрузить app.yaml с учётом переменных окружения IPTV_*."""
    config_dir = config_dir or Path(os.environ.get("IPTV_CONFIG_DIR", _DEFAULT_CONFIG_DIR))
    raw = read_yaml(config_dir / "app.yaml")

    raw.setdefault("config_dir", config_dir)
    # Разделы app.yaml верхнего уровня.
    for section in ("app", "paths", "check", "storage", "retention", "scoring", "geo"):
        raw.setdefault(section, {})

    paths = raw["paths"]
    if env := os.environ.get("IPTV_DATA_DIR"):
        paths["data_dir"] = env
    if env := os.environ.get("IPTV_DIST_DIR"):
        paths["dist_dir"] = env
    if env := os.environ.get("IPTV_PROBE_LOCATION"):
        raw["probe_location"] = env
    if env := os.environ.get("IPTV_LOG_LEVEL"):
        raw["app"]["log_level"] = env
    if env := os.environ.get("IPTV_STORAGE"):
        raw["storage"]["backend"] = env
    if env := os.environ.get("IPTV_SQLITE_PATH"):
        raw["storage"]["sqlite_path"] = env
    if env := os.environ.get("IPTV_JSONL_PATH"):
        raw["storage"]["jsonl_path"] = env

    raw.update(overrides)
    return AppSettings.model_validate(raw)


# --- sources.yaml -----------------------------------------------------------


def load_sources(config_dir: Path) -> list[SourceConfig]:
    """Загрузить описания источников IPTV."""
    raw = read_yaml(config_dir / "sources.yaml")
    entries = raw.get("sources", [])
    return [SourceConfig.model_validate(entry) for entry in entries]


# --- categories.yaml ---------------------------------------------------------


class CategoryRule(BaseModel):
    """Правило сопоставления: категории соответствуют подстроки-паттерны."""

    category: Category
    patterns: list[str]


class CategoriesFile(BaseModel):
    rules: list[CategoryRule]
    default_category: Category = Category.GENERAL


def load_categories(config_dir: Path) -> CategoriesFile:
    raw = read_yaml(config_dir / "categories.yaml")
    rules = [
        CategoryRule(category=item["category"], patterns=item["patterns"])
        for item in raw.get("categories", [])
    ]
    default = raw.get("default_category", "general")
    return CategoriesFile(rules=rules, default_category=Category(default))


# --- quality_profiles.yaml ---------------------------------------------------


class QualityWeights(BaseModel):
    availability: float = 0.35
    stability: float = 0.30
    startup: float = 0.15
    media: float = 0.15
    hls: float = 0.05


class QualityLevels(BaseModel):
    excellent: int = 90
    good: int = 75
    unstable: int = 50


class ApprovalSettings(BaseModel):
    """Критерии кандидатов на подтверждение публикации.

    Кандидат — поток с рейтингом, проверенный минимум из двух точек
    наблюдения и отдавший HLS-сегмент. Подтверждение выполняет человек
    (merge PR от workflow approve-candidates).
    """

    min_score: float = 75
    min_checks: int = 6
    min_probe_locations: int = 2
    require_segment: bool = True
    max_per_run: int = 50


class QualityProfileSettings(BaseModel):
    """Профиль отбора потоков в публичную сборку."""

    country: str
    min_score: int = 50
    min_checks: int = 5
    min_height: int | None = None
    categories: list[Category] | None = None


class QualityFile(BaseModel):
    weights: QualityWeights = Field(default_factory=QualityWeights)
    levels: QualityLevels = Field(default_factory=QualityLevels)
    profiles: dict[str, QualityProfileSettings] = Field(default_factory=dict)
    approval: ApprovalSettings = Field(default_factory=ApprovalSettings)

    def profile(self, profile_id: str) -> QualityProfileSettings:
        try:
            return self.profiles[profile_id]
        except KeyError as exc:
            raise KeyError(
                f"quality profile {profile_id!r} not found; available: {sorted(self.profiles)}"
            ) from exc


def load_quality(config_dir: Path) -> QualityFile:
    raw = read_yaml(config_dir / "quality_profiles.yaml")
    profiles = {
        pid: QualityProfileSettings.model_validate({"country": body.get("country", ""), **body})
        for pid, body in raw.get("profiles", {}).items()
    }
    return QualityFile(
        weights=QualityWeights.model_validate(raw.get("weights", {})),
        levels=QualityLevels.model_validate(raw.get("levels", {})),
        profiles=profiles,
        approval=ApprovalSettings.model_validate(raw.get("approval", {})),
    )


# --- countries/<cc>.yaml -----------------------------------------------------


class CountryPlaylist(BaseModel):
    profile: str
    filename: str
    title: str | None = None


class AliasRule(BaseModel):
    """Ручной алиас: каноническое название канала -> tvg_id EPG."""

    name: str
    tvg_id: str
    manual: bool = True


class CountryProfile(BaseModel):
    """Профиль страны: плейлисты, EPG, алиасы."""

    country: str
    name: str = ""
    languages: list[str] = Field(default_factory=list)
    playlists: list[CountryPlaylist] = Field(default_factory=list)
    epg_filename: str | None = None
    aliases: list[AliasRule] = Field(default_factory=list)
    # Ручные номера каналов для tvg-chno (issue #7). Ключ — имя или его
    # устойчивая часть; номер резервируется до hash-нумерации остальных.
    channel_numbers: dict[str, int] = Field(default_factory=dict)


def load_country(config_dir: Path, country: str) -> CountryProfile:
    path = config_dir / "countries" / f"{country.lower()}.yaml"
    raw = read_yaml(path)
    if not raw:
        raise FileNotFoundError(f"country profile not found: {path}")
    return CountryProfile.model_validate(raw)


def available_countries(config_dir: Path) -> list[str]:
    """Список стран с профилями (файлы config/countries/*.yaml)."""
    directory = config_dir / "countries"
    if not directory.is_dir():
        return []
    return sorted(p.stem.upper() for p in directory.glob("*.yaml"))


# --- epg_sources.yaml / logo_sources.yaml ------------------------------------


class EpgSource(BaseModel):
    id: str
    enabled: bool = False
    format: str = "xmltv"
    url: str
    trust_level: float = 0.5
    license_note: str | None = None


class NameBridgeSettings(BaseModel):
    """Мост имён iptv-org/database (ключ name_bridge в epg_sources.yaml)."""

    enabled: bool = False
    url: str = "https://raw.githubusercontent.com/iptv-org/database/master/data/channels.csv"


class LogoSource(BaseModel):
    id: str
    enabled: bool = False
    type: str = "url_pattern"
    url_template: str
    trust_level: float = 0.5
    max_bytes: int = 2_097_152
    allowed_mime: list[str] = Field(default_factory=list)
    license_note: str | None = None


class LogoOverride(BaseModel):
    name: str
    logo_url: str


class LogoSourcesFile(BaseModel):
    sources: list[LogoSource] = Field(default_factory=list)
    overrides: list[LogoOverride] = Field(default_factory=list)


def load_epg_sources(config_dir: Path) -> list[EpgSource]:
    raw = read_yaml(config_dir / "epg_sources.yaml")
    return [EpgSource.model_validate(item) for item in raw.get("epg_sources", [])]


def load_logo_sources(config_dir: Path) -> LogoSourcesFile:
    raw = read_yaml(config_dir / "logo_sources.yaml")
    return LogoSourcesFile(
        sources=[LogoSource.model_validate(item) for item in raw.get("logo_sources", [])],
        overrides=[LogoOverride.model_validate(item) for item in raw.get("overrides", [])],
    )


def load_name_bridge(config_dir: Path) -> NameBridgeSettings:
    """Мост имён: ключ name_bridge в epg_sources.yaml (issue #5)."""
    raw = read_yaml(config_dir / "epg_sources.yaml")
    return NameBridgeSettings.model_validate(raw.get("name_bridge") or {})


__all__ = [
    "AliasRule",
    "ApprovalSettings",
    "AppSettings",
    "CategoriesFile",
    "CategoryRule",
    "CountryPlaylist",
    "CountryProfile",
    "EpgSource",
    "LifecycleSettings",
    "LogoOverride",
    "LogoSource",
    "NameBridgeSettings",
    "LogoSourcesFile",
    "PublicPolicy",
    "QualityFile",
    "QualityLevels",
    "QualityProfileSettings",
    "QualityWeights",
    "SourceConfig",
    "available_countries",
    "load_categories",
    "load_country",
    "load_epg_sources",
    "load_logo_sources",
    "load_name_bridge",
    "load_quality",
    "load_settings",
    "load_sources",
    "read_yaml",
]
