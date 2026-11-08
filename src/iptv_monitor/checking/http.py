"""Уровень 1 — быстрая HTTP-проверка.

DNS/TCP/TLS, HTTP-код и заголовки, редиректы и тайм-ауты, ограничение
размера ответа. Реализация запроса — infrastructure.http_client.fetch
(SSRF-защита, ограничение тела, ручные проверенные редиректы).
"""

from __future__ import annotations

import httpx

from ..domain.enums import CheckErrorCode
from ..infrastructure.http_client import FetchResult, fetch


async def check_http(
    url: str,
    client: httpx.AsyncClient,
    *,
    max_bytes: int = 65536,
    max_redirects: int = 5,
) -> FetchResult:
    """Выполнить ограниченный GET-запрос к потоку."""
    return await fetch(client, url, max_bytes=max_bytes, max_redirects=max_redirects)


def classify_http(result: FetchResult) -> tuple[CheckErrorCode | None, str | None]:
    """Классифицировать HTTP-результат в код ошибки CheckResult."""
    if result.error_code:
        return result.error_code, result.error_message
    if result.status >= 500:
        return CheckErrorCode.HTTP_5XX, f"http {result.status}"
    if result.status >= 400:
        return CheckErrorCode.HTTP_4XX, f"http {result.status}"
    return None, None
