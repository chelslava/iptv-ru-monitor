"""Единый реестр секретных ключей query-параметров (issue #25).

Один источник для редакции логов (infrastructure.logging) и политики
публикации (filtering.publication_policy) — раньше списки дублировались
и дрейфовали: username Xtream-URL не маскировался нигде, хотя в этой
схеме username и есть учётные данные.
"""

from __future__ import annotations

import re

# Параметры, значения которых маскируются в логах и запрещают публикацию URL.
# username/password — Xtream-Codes (?username=...&password=...);
# user/login — вариации; session/sid/cid/st/hmac/session_id — токены
# стриминговых CDN и middleware.
TOKEN_KEYS: frozenset[str] = frozenset(
    {
        "token",
        "key",
        "auth",
        "signature",
        "password",
        "pwd",
        "secret",
        "expires",
        "expire",
        "jwt",
        "access_token",
        "api_key",
        "hash",
        "username",
        "user",
        "login",
        "session",
        "session_id",
        "sid",
        "cid",
        "st",
        "hmac",
        "auth_key",
    }
)

# Значения, похожие на токен/base64 (≥24 символов из алфавита токенов).
TOKEN_VALUE_RE = re.compile(r"^[A-Za-z0-9_\-\.]{24,}$")

MASK = "***"
