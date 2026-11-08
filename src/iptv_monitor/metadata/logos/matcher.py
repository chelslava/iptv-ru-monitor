"""Сопоставление логотипов каналов.

Приоритет — доверенным каталогам; локальные переопределения побеждают
автоматические совпадения. Копирование изображений в публичный каталог
при неясных правах не выполняется: хранится URL и происхождение.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from ...domain.channel import Channel
from ...domain.enums import MatchMethod
from ...normalization.channel_names import normalize_name
from ...settings import LogoOverride, LogoSource

logger = logging.getLogger(__name__)


@dataclass
class LogoMatch:
    """Решение о логотипе канала."""

    channel_id: str
    logo_url: str
    source_id: str
    method: MatchMethod
    confidence: float
    manual: bool


def match_logos(
    channels: list[Channel],
    sources: list[LogoSource],
    overrides: list[LogoOverride],
) -> list[LogoMatch]:
    """Подобрать логотипы каналам, у которых их нет."""
    override_by_name = {normalize_name(o.name): o for o in overrides}
    pattern_sources = [s for s in sources if s.enabled and s.type == "url_pattern"]
    matches: list[LogoMatch] = []

    for channel in channels:
        if channel.logo_url:
            continue  # происхождение уже зафиксировано источником

        override = override_by_name.get(normalize_name(channel.name)) or next(
            (
                override_by_name[get]
                for alt in channel.alt_names
                if (get := normalize_name(alt)) in override_by_name
            ),
            None,
        )
        if override is not None:
            matches.append(
                LogoMatch(
                    channel_id=channel.channel_id,
                    logo_url=override.logo_url,
                    source_id="override",
                    method=MatchMethod.MANUAL,
                    confidence=1.0,
                    manual=True,
                )
            )
            continue

        if channel.tvg_id:
            for source in pattern_sources:
                url = source.url_template.format(tvg_id=channel.tvg_id)
                matches.append(
                    LogoMatch(
                        channel_id=channel.channel_id,
                        logo_url=url,
                        source_id=source.id,
                        method=MatchMethod.TVG_ID,
                        confidence=source.trust_level,
                        manual=False,
                    )
                )
                break

    return matches


async def validate_logo(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int,
    allowed_mime: list[str],
) -> bool:
    """Проверить доступность логотипа, MIME-тип и размер (HEAD + Range)."""
    try:
        response = await client.head(url, follow_redirects=True)
        if response.status_code >= 400:
            return False
        content_type = response.headers.get("content-type", "").split(";")[0].strip()
        length = response.headers.get("content-length")
        if allowed_mime and content_type and content_type not in allowed_mime:
            return False
        if length and length.isdigit() and int(length) > max_bytes:
            return False
        return True
    except httpx.HTTPError:
        logger.debug("logo validation failed: %s", url)
        return False
