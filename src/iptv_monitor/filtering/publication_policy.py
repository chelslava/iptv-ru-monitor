"""Политика публикации: допуск канала/потока к публичной сборке.

Правила:
- секретные URL (токены, ключи, userinfo) не публикуются никогда;
- поток отклонённый вручную (publication_status=rejected) не публикуется;
- источник с политикой review публикуется только после подтверждения
  (data/state/approved_streams.yaml);
- источник с политикой deny не публикуется никогда.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import yaml

from ..domain.channel import Channel
from ..domain.enums import PublicationStatus, PublicPolicy
from ..domain.source import SourceConfig
from ..domain.stream import Stream
from ..infrastructure.secrets import TOKEN_KEYS, TOKEN_VALUE_RE

APPROVED_STREAMS_FILENAME = "approved_streams.yaml"


def url_has_secrets(url: str) -> str | None:
    """Вернуть описание секрета в URL либо None, если URL безопасен."""
    parts = urlsplit(url)
    if parts.username or parts.password:
        return "url contains credentials"
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in TOKEN_KEYS:
            return f"secret query parameter {key!r}"
        if TOKEN_VALUE_RE.match(value):
            return f"token-like query parameter {key!r}"
    return None


@dataclass
class PublishDecision:
    """Решение о публикации потока с перечнем причин."""

    allowed: bool
    reasons: list[str] = field(default_factory=list)


def decide_publication(
    channel: Channel,
    stream: Stream,
    source: SourceConfig | None,
    approved_ids: set[str] | None = None,
    *,
    denied_consecutive_failures: int | None = None,
) -> PublishDecision:
    """Принять решение о допуске потока к публичной сборке.

    denied_consecutive_failures — провалы подряд, достигшие порога
    автодeny (issue #8). Порог задаётся в config/app.yaml (lifecycle);
    approved-запись при этом не удаляется — восстановление происходит
    автоматически после первого успешного чека.
    """
    reasons: list[str] = []
    approved_ids = approved_ids or set()

    if not stream.enabled:
        reasons.append("stream disabled")
    if stream.publication_status == PublicationStatus.REJECTED:
        reasons.append("stream rejected manually")

    if denied_consecutive_failures is not None and denied_consecutive_failures > 0:
        reasons.append(f"auto-denied ({denied_consecutive_failures} consecutive failures)")

    # Подтверждение review-источника и есть допуск канала к публикации:
    # без is_public у review-источников подтверждение не имело бы силы.
    approved_review = bool(
        source and source.public_policy == PublicPolicy.REVIEW and stream.stream_id in approved_ids
    )
    if not channel.is_public and not approved_review:
        reasons.append("channel is not public")

    secret = url_has_secrets(stream.url)
    if secret:
        reasons.append(f"secret url: {secret}")

    if source is None:
        reasons.append("source not found in config")
    else:
        policy = source.public_policy
        if policy == PublicPolicy.DENY:
            reasons.append(f"source policy denies publication ({source.id})")
        elif policy == PublicPolicy.REVIEW and not approved_review:
            reasons.append(f"awaiting review approval (source {source.id})")
        # ALLOW — публикация разрешена.

    return PublishDecision(allowed=not reasons, reasons=reasons)


def load_approved_ids(state_dir: Path) -> set[str]:
    """Загрузить подтверждённые stream_id из data/state/approved_streams.yaml."""
    path = state_dir / APPROVED_STREAMS_FILENAME
    if not path.is_file():
        return set()
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if isinstance(data, list):
        return {str(item) for item in data}
    return {str(item) for item in data.get("stream_ids", [])}
