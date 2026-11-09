"""Интеграционный тест: полный конвейер discover → check → score → build без сети."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from iptv_monitor.cli import run_build, run_check, run_discover, run_score
from iptv_monitor.settings import (
    AppSettings,
    CheckSettings,
    GeoSettings,
    PathsConfig,
    ScoringSettings,
    StorageSettings,
)

pytestmark = pytest.mark.usefixtures("fake_dns_guard")

REPO_ROOT = Path(__file__).parents[2]
FIXTURE_M3U = REPO_ROOT / "tests" / "fixtures" / "ru_sample.m3u"

MEDIA_PLAYLIST = "#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:5.0,\nseg1.ts\n"


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.endswith(".m3u8"):
        if "match" in url:
            return httpx.Response(403, text="geo-blocked")
        if "karusel" in url:
            return httpx.Response(200, text="<html>broken</html>")
        return httpx.Response(
            200,
            headers={"content-type": "application/vnd.apple.mpegurl"},
            text=MEDIA_PLAYLIST,
        )
    if url.endswith(".ts"):
        return httpx.Response(200, content=b"\x47" * 4096)
    if "news24" in url:
        return httpx.Response(200, headers={"content-type": "video/mp2t"}, content=b"\x47" * 4096)
    return httpx.Response(404)


@pytest.fixture
def env(tmp_path: Path) -> SimpleNamespace:
    """Изолированное окружение: конфигурация, состояние, dist."""
    config_dir = tmp_path / "config"
    countries_dir = config_dir / "countries"
    countries_dir.mkdir(parents=True)

    # Переиспользуем репозиторные правила категорий, профили и страну.
    shutil.copy(REPO_ROOT / "config" / "categories.yaml", config_dir / "categories.yaml")
    shutil.copy(
        REPO_ROOT / "config" / "quality_profiles.yaml", config_dir / "quality_profiles.yaml"
    )
    shutil.copy(REPO_ROOT / "config" / "countries" / "ru.yaml", countries_dir / "ru.yaml")

    # Единственный источник — локальный фикстурный M3U с политикой allow.
    (config_dir / "sources.yaml").write_text(
        "sources:\n"
        "  - id: test-custom\n"
        "    adapter: custom_m3u\n"
        "    enabled: true\n"
        "    country: RU\n"
        "    public_policy: allow\n"
        f'    path: "{FIXTURE_M3U.as_posix()}"\n',
        encoding="utf-8",
    )

    data_dir = tmp_path / "data"
    settings = AppSettings(
        config_dir=config_dir,
        paths=PathsConfig(data_dir=data_dir, dist_dir=tmp_path / "dist"),
        probe_location="test-runner",
        check=CheckSettings(concurrency=4, http_timeout_seconds=5.0),
        storage=StorageSettings(
            backend="jsonl",
            jsonl_path=data_dir / "state" / "checks.jsonl",
            sqlite_path=data_dir / "state" / "history.sqlite",
        ),
        geo=GeoSettings(ip_info_url=None),
        scoring=ScoringSettings(min_checks=5),
    )
    return SimpleNamespace(settings=settings, tmp_path=tmp_path)


def test_full_pipeline(env: SimpleNamespace) -> None:
    settings = env.settings

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        # Этап 1 — discovery и нормализация.
        channels, streams = run_discover(settings, client)
        assert len(channels) == 6
        assert len(streams) == 7
        assert (settings.state_dir / "channels.json").is_file()
        assert (settings.state_dir / "streams.json").is_file()

        # Этап 2 — многократные проверки (история для скоринга).
        for _ in range(6):
            results = run_check(settings, levels=("http", "hls"), client=client)
            assert len(results) == 7
    finally:
        asyncio.run(client.aclose())

    history_file = settings.storage.jsonl_path
    assert history_file.is_file()

    # Этап 3 — скоринг.
    scores = run_score(settings)
    assert (settings.state_dir / "scores.json").is_file()
    assert len(scores) == 7

    # Этап 4 — сборка.
    run_build(settings, country="RU")

    dist_ru = settings.dist_dir / "ru"
    m3u_text = (dist_ru / "russia.m3u").read_text(encoding="utf-8")
    assert m3u_text.startswith("#EXTM3U")
    assert "1tv.ru" in m3u_text  # tvg-id из источника попал в плейлист
    # Один лучший поток на канал (issue #6): у «Первый канал» два здоровых
    # потока, в плейлисте ровно один.
    assert m3u_text.count('tvg-id="1tv.ru"') == 1
    assert "stream.example.org/1tv" in m3u_text or "mirror.example.org" in m3u_text
    assert "matchtv.ru" not in m3u_text  # 403 -> исключён
    assert "token=" not in m3u_text  # секретный URL не опубликован
    assert 'tvg-chno="' in m3u_text  # стабильная нумерация (issue #7)
    assert (dist_ru / "russia-kids.m3u").is_file()
    assert (dist_ru / "channels.json").is_file()
    assert (settings.dist_dir / "index.html").is_file()

    # Отчёт объясняет, почему потоки исключены.
    report = json.loads((dist_ru / "report.json").read_text(encoding="utf-8"))
    excluded = [s for s in report["streams"] if not s["included"]]
    assert excluded, "ожидались исключённые потоки"
    reasons = " ".join(reason for s in excluded for reason in (s["reasons"] or []))
    assert "secret" in reasons
    assert "score" in reasons or "below" in reasons
    assert "superseded" in reasons  # проигравший поток канала объяснён (#6)

    # Публичный streams.json не содержит URL исключённых потоков.
    streams_json = json.loads((dist_ru / "streams.json").read_text(encoding="utf-8"))
    excluded_entries = [s for s in streams_json if not s["included"]]
    assert excluded_entries
    assert all(entry["url"] is None for entry in excluded_entries)

    # Результаты содержат точку наблюдения.
    with history_file.open(encoding="utf-8") as fh:
        first_line = json.loads(fh.readline())
    assert first_line["probe_location"] == "test-runner"


def test_build_single_profile(env: SimpleNamespace) -> None:
    settings = env.settings
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        run_discover(settings, client)
        for _ in range(6):
            run_check(settings, levels=("http",), client=client)
    finally:
        asyncio.run(client.aclose())
    run_score(settings)
    run_build(settings, country="RU", only_profile="ru_hd")

    dist_ru = settings.dist_dir / "ru"
    assert (dist_ru / "russia-hd.m3u").is_file()
    # Остальные плейлисты при фильтре по профилю не собираются.
    assert not (dist_ru / "russia.m3u").exists()
