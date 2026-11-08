"""Тесты нормализации названий и кодов стран."""

from __future__ import annotations

import pytest

from iptv_monitor.normalization.channel_names import build_channel_id, normalize_name
from iptv_monitor.normalization.country import normalize_country


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Первый канал HD", "первый канал"),
        ("Россия 1 (эфир)", "россия 1"),
        ("Канал [1080p]", "канал"),
        ("Пятый канал", "пятый канал"),
        ("Муз ТВ", "муз тв"),
        ("  Лента   4К  ", "лента"),
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


def test_channel_id_is_stable() -> None:
    first = build_channel_id("Первый канал HD", "RU")
    second = build_channel_id("Первый канал", "RU")
    assert first == second
    assert first.startswith("ru-")


def test_channel_id_differs_between_countries() -> None:
    assert build_channel_id("Первый канал", "RU") != build_channel_id("Первый канал", "KZ")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ru", "RU"),
        (" Ru ", "RU"),
        ("RUS", None),
        ("", None),
        (None, None),
        ("1A", None),
    ],
)
def test_normalize_country(raw: str | None, expected: str | None) -> None:
    assert normalize_country(raw) == expected
