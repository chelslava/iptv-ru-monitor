"""Фабрика HTTP-клиента и SSRF-защита.

Сторонний URL — недоверенный ввод. Запрещены обращения к localhost, приватным,
link-local и служебным IP-диапазонам, включая каждую цепочку редиректов,
чтобы проверяющий не мог использоваться для доступа к внутренним сервисам.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpcore
import httpx

from ..domain.enums import CheckErrorCode

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_SCHEMES = {"http", "https"}


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Соединяется только с IP, проверенными SSRF-защитой, в момент соединения.

    Закрывает DNS-rebinding TOCTOU (issue #23): validate_url перед запросом
    резолвит имя, но httpx резолвит второй раз при подключении — перебинденный
    DNS мог успеть вернуть приватный IP. Здесь разрешение и проверка
    выполняются в момент TCP-соединения, после чего соединение открывается
    к проверенному адресу (внутренний AnyIO-backend сам резолвит IP-литерал
    тривиально). TLS SNI и верификация сертификата остаются по имени хоста —
    start_tls делает пул с оригинальным hostname.

    Ошибки SSRF на этом уровне классифицируются как transport_error:
    fetch() предварительно валидирует URL и даёт точные коды; этот backend —
    страховка именно на гонку между проверкой и соединением.
    """

    def __init__(self) -> None:
        self._inner = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: object | None = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            ips = (
                [host]
                if _is_ip_literal(host)
                else await asyncio.to_thread(resolve_hostname, host, port)
            )
        except socket.gaierror as exc:
            raise httpcore.ConnectError(f"dns resolution failed: {host}") from exc

        allowed: list[str] = []
        for ip_str in ips:
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError as exc:
                raise httpcore.ConnectError(f"unparseable address {ip_str!r}") from exc
            if is_forbidden_ip(ip):
                raise httpcore.ConnectError(f"ssrf pinned backend: forbidden ip range ({ip})")
            allowed.append(ip_str)
        if not allowed:
            raise httpcore.ConnectError("ssrf pinned backend: empty dns answer")

        last_exc: Exception | None = None
        for ip_str in allowed:
            try:
                return await self._inner.connect_tcp(
                    ip_str, port, timeout=timeout, local_address=local_address
                )
            except (httpcore.ConnectError, OSError) as exc:
                last_exc = exc
        raise last_exc or httpcore.ConnectError(f"no connectable address for {host}")


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


class UrlGuardError(Exception):
    """URL запрещён политикой SSRF-защиты либо не разрешается по DNS."""

    def __init__(self, url: str, reason: str, error_code: CheckErrorCode) -> None:
        super().__init__(f"{reason}: {self._sanitize(url)}")
        self.url = url
        self.reason = reason
        self.error_code = error_code

    @staticmethod
    def _sanitize(url: str) -> str:
        # В сообщении ошибки не должно остаться токенов из query string.
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.hostname or 'host'}{parsed.path}"


def is_forbidden_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Запрещён ли IP: приватные, loopback, link-local, служебные диапазоны."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def _validate_parsed_url(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    if parsed.scheme not in _SCHEMES:
        raise UrlGuardError(url, "unsupported scheme", CheckErrorCode.UNSUPPORTED_SCHEME)
    if not parsed.hostname:
        raise UrlGuardError(url, "no hostname", CheckErrorCode.UNSUPPORTED_SCHEME)
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise UrlGuardError(url, "invalid port", CheckErrorCode.UNSUPPORTED_SCHEME) from exc
    return parsed.hostname, port


def _check_ip_literals(url: str, hostname: str) -> None:
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return  # обычное доменное имя, проверим после разрешения
    if is_forbidden_ip(ip):
        raise UrlGuardError(url, f"forbidden ip range ({ip})", CheckErrorCode.SSRF_BLOCKED)


def resolve_hostname(hostname: str, port: int) -> list[str]:
    """Синхронно разрешить имя во все адреса (getaddrinfo)."""
    infos = socket.getaddrinfo(hostname, port, 0, socket.SOCK_STREAM)
    addresses: set[str] = set()
    for info in infos:
        host = info[4][0]
        addresses.add(host if isinstance(host, str) else str(host))
    return sorted(addresses)


def validate_url_sync(url: str) -> list[str]:
    """Проверить URL SSRF-защитой, вернуть разрешённые IP.

    Бросает UrlGuardError с классифицированной причиной.
    """
    hostname, port = _validate_parsed_url(url)
    _check_ip_literals(url, hostname)
    try:
        ips = resolve_hostname(hostname, port)
    except socket.gaierror as exc:
        raise UrlGuardError(url, "dns resolution failed", CheckErrorCode.DNS_ERROR) from exc
    if not ips:
        raise UrlGuardError(url, "empty dns answer", CheckErrorCode.DNS_ERROR)
    for ip_str in ips:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise UrlGuardError(
                url, f"unparseable address {ip_str!r}", CheckErrorCode.DNS_ERROR
            ) from exc
        if is_forbidden_ip(ip):
            raise UrlGuardError(url, f"forbidden ip range ({ip})", CheckErrorCode.SSRF_BLOCKED)
    return ips


async def validate_url(url: str) -> list[str]:
    """Асинхронная версия validate_url_sync (DNS в отдельном потоке)."""
    return await asyncio.to_thread(validate_url_sync, url)


def create_client(
    *,
    user_agent: str = "iptv-ru-monitor",
    timeout_seconds: float = 10.0,
    verify: bool = True,
) -> httpx.AsyncClient:
    """HTTP-клиент с тайм-аутами; редиректы обрабатываются вручную (см. fetch).

    Транспорт с pinned-бэкендом (issue #23): DNS проверяется и закрепляется
    в момент TCP-соединения — DNS-rebinding между validate_url и connect не
    проходит.
    """
    timeout = httpx.Timeout(connect=5.0, read=timeout_seconds, write=5.0, pool=5.0)
    transport = httpx.AsyncHTTPTransport(verify=verify, retries=0)
    # httpx 0.28 не прокидывает network_backend в пул — устанавливаем
    # непосредственно (httpcore.AsyncConnectionPool._network_backend).
    transport._pool._network_backend = _PinnedNetworkBackend()  # noqa: SLF001
    return httpx.AsyncClient(
        headers={"User-Agent": user_agent},
        timeout=timeout,
        follow_redirects=False,
        verify=verify,
        transport=transport,
    )


@dataclass
class FetchResult:
    """Результат ограниченного GET-запроса."""

    url: str
    status: int
    headers: httpx.Headers = field(default_factory=httpx.Headers)
    body: bytes = b""
    final_url: str = ""
    redirects: int = 0
    elapsed_ms: int = 0
    dns_ok: bool | None = None
    tls_ok: bool | None = None
    error_code: CheckErrorCode | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.error_code is None and self.status < 400


async def fetch(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int = 65536,
    max_redirects: int = 5,
    extra_headers: dict[str, str] | None = None,
    guard: bool = True,
    timeout_seconds: float | None = None,
) -> FetchResult:
    """GET с ограничением читаемых байт и ручной проверкой редиректов.

    Ограничение тела защищает от «бесконечных» MPEG-TS ответов. Каждый
    редирект проходит SSRF-проверку заново. ``timeout_seconds`` — тайм-аут
    на уровне запроса (читается из check.hls_timeout_seconds /
    check.segment_timeout_seconds, issue #26); None — тайм-аут клиента.
    """
    started = time.perf_counter()
    current = url
    redirects = 0
    dns_ok: bool | None = None
    tls_ok: bool | None = None

    try:
        while True:
            if guard:
                await validate_url(current)
                dns_ok = True

            is_https = urlparse(current).scheme == "https"
            try:
                if timeout_seconds is not None:
                    response_ctx = client.stream(
                        "GET",
                        current,
                        headers=extra_headers,
                        follow_redirects=False,
                        timeout=timeout_seconds,
                    )
                else:
                    response_ctx = client.stream(
                        "GET", current, headers=extra_headers, follow_redirects=False
                    )
                async with response_ctx as response:
                    if is_https:
                        tls_ok = True
                    if response.status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            # Редирект без Location — переходить некуда, ответ
                            # терминальный. Раньше здесь были TypeError
                            # (urljoin(current, None)) или бесконечный цикл
                            # для пустого Location (issue #19).
                            return FetchResult(
                                url=url,
                                status=response.status_code,
                                final_url=current,
                                redirects=redirects,
                                elapsed_ms=int((time.perf_counter() - started) * 1000),
                                dns_ok=dns_ok,
                                tls_ok=tls_ok,
                                error_code=CheckErrorCode.REDIRECT_INVALID,
                                error_message=f"redirect {response.status_code} without location",
                            )
                        redirects += 1
                        if redirects > max_redirects:
                            return FetchResult(
                                url=url,
                                status=response.status_code,
                                final_url=current,
                                redirects=redirects,
                                elapsed_ms=int((time.perf_counter() - started) * 1000),
                                dns_ok=dns_ok,
                                tls_ok=tls_ok,
                                error_code=CheckErrorCode.REDIRECT_LIMIT,
                                error_message=f"more than {max_redirects} redirects",
                            )
                        current = urljoin(current, location)
                        continue
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body += chunk[: max_bytes - len(body)]
                        if len(body) >= max_bytes:
                            break
                    return FetchResult(
                        url=url,
                        status=response.status_code,
                        headers=response.headers,
                        body=bytes(body),
                        final_url=str(response.url),
                        redirects=redirects,
                        elapsed_ms=int((time.perf_counter() - started) * 1000),
                        dns_ok=dns_ok,
                        tls_ok=tls_ok,
                    )
            except ssl.SSLError as exc:
                return FetchResult(
                    url=url,
                    status=0,
                    redirects=redirects,
                    elapsed_ms=0,
                    dns_ok=dns_ok,
                    tls_ok=False,
                    error_code=CheckErrorCode.TLS_ERROR,
                    error_message=str(exc),
                )
            except httpx.TimeoutException as exc:
                return FetchResult(
                    url=url,
                    status=0,
                    redirects=redirects,
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    dns_ok=dns_ok,
                    tls_ok=tls_ok,
                    error_code=CheckErrorCode.TIMEOUT,
                    error_message=type(exc).__name__,
                )
            except httpx.ConnectError as exc:
                code = (
                    CheckErrorCode.TLS_ERROR
                    if "ssl" in str(exc).lower()
                    else (CheckErrorCode.TRANSPORT_ERROR)
                )
                return FetchResult(
                    url=url,
                    status=0,
                    redirects=redirects,
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    dns_ok=dns_ok,
                    tls_ok=tls_ok,
                    error_code=code,
                    error_message=type(exc).__name__,
                )
            except httpx.HTTPError as exc:
                return FetchResult(
                    url=url,
                    status=0,
                    redirects=redirects,
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    dns_ok=dns_ok,
                    tls_ok=tls_ok,
                    error_code=CheckErrorCode.TRANSPORT_ERROR,
                    error_message=type(exc).__name__,
                )
    except UrlGuardError as exc:
        dns_flag = exc.error_code != CheckErrorCode.DNS_ERROR
        return FetchResult(
            url=url,
            status=0,
            redirects=redirects,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            dns_ok=None if dns_flag else False,
            error_code=exc.error_code,
            error_message=exc.reason,
        )
