"""Географический контекст проверки (точка наблюдения и страна)."""

from __future__ import annotations

import logging
import os

import httpx

from ..settings import AppSettings

logger = logging.getLogger(__name__)

KNOWN_PROBE_LOCATIONS = ("github-runner", "home-ru", "ru-vds", "local")


def resolve_probe_location(explicit: str | None = None, settings: AppSettings | None = None) -> str:
    """Определить метку точки наблюдения.

    Приоритет: явный аргумент > конфигурация/окружение > эвристика
    (GitHub Actions → github-runner, иначе local). GitHub-hosted runner
    не считается российской точкой проверки и маркируется отдельно.
    Опечатка в явной метке не проходит молча (issue #26): предупреждение
    в лог; свободные метки не запрещены — их заводят новые точки.
    """
    if explicit:
        if explicit not in KNOWN_PROBE_LOCATIONS:
            logger.warning(
                "unknown probe location %r (known: %s) — проверьте опечатки",
                explicit,
                ", ".join(KNOWN_PROBE_LOCATIONS),
            )
        return explicit
    if settings and settings.probe_location and settings.probe_location != "local":
        return settings.probe_location
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return "github-runner"
    return settings.probe_location if settings else "local"


async def detect_country_code(client: httpx.AsyncClient, ip_info_url: str | None) -> str | None:
    """Определить страну исходящего адреса через внешний сервис (необязательно)."""
    if not ip_info_url:
        return None
    try:
        response = await client.get(ip_info_url, follow_redirects=True)
        response.raise_for_status()
        code = response.json().get("country")
    except (httpx.HTTPError, ValueError):
        logger.warning("country code detection failed", exc_info=True)
        return None
    return code if isinstance(code, str) else None
