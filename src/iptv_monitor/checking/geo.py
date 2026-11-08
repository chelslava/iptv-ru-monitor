"""Географический контекст проверки (точка наблюдения и страна)."""

from __future__ import annotations

import logging
import os

import httpx

from ..settings import AppSettings

logger = logging.getLogger(__name__)

KNOWN_PROBE_LOCATIONS = ("github-runner", "ru-vds", "local")


def resolve_probe_location(explicit: str | None = None, settings: AppSettings | None = None) -> str:
    """Определить метку точки наблюдения.

    Приоритет: явный аргумент > конфигурация/окружение > эвристика
    (GitHub Actions → github-runner, иначе local). GitHub-hosted runner
    не считается российской точкой проверки и маркируется отдельно.
    """
    if explicit:
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
