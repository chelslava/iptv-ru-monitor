"""Инфраструктура: HTTP-клиент, логирование, хранилища."""

from .http_client import (
    FetchResult,
    UrlGuardError,
    create_client,
    fetch,
    is_forbidden_ip,
    validate_url,
    validate_url_sync,
)
from .logging import RedactingFilter, redact_text, redact_url, setup_logging
from .storage import CheckStorage, JsonlStorage, SqliteStorage, create_storage

__all__ = [
    "CheckStorage",
    "FetchResult",
    "JsonlStorage",
    "RedactingFilter",
    "SqliteStorage",
    "UrlGuardError",
    "create_client",
    "create_storage",
    "fetch",
    "is_forbidden_ip",
    "redact_text",
    "redact_url",
    "setup_logging",
    "validate_url",
    "validate_url_sync",
]
