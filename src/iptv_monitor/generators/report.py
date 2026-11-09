"""Машинно-читаемый отчёт, статистика и статическая index-страница."""

from __future__ import annotations

import html
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from .. import __version__
from ..domain.check_result import CheckResult
from ..filtering import SelectedStream
from ..history.lifecycle import StreamLifecycle


def _uptime_percent(
    by_stream: dict[str, list[CheckResult]],
    stream_id: str,
    days: int,
    now: datetime,
) -> float | None:
    """% успешных проверок потока за окно (issue #9); None — нет данных."""
    window = [r for r in by_stream.get(stream_id, []) if r.checked_at >= now - timedelta(days=days)]
    if not window:
        return None
    return round(100 * sum(1 for r in window if r.is_success()) / len(window), 1)


def build_report(
    *,
    country: str,
    profile_id: str,
    selections: list[SelectedStream],
    results: Iterable[CheckResult],
    generated_at: datetime,
    lifecycle: dict[str, StreamLifecycle] | None = None,
) -> dict[str, object]:
    """Отчёт, объясняющий, почему поток включён или исключён."""
    results = list(results)
    error_codes = Counter(r.error_code.value for r in results if r.error_code is not None)
    probe_locations = Counter(r.probe_location for r in results)
    levels = Counter((sel.score.level.value if sel.score else "no_history") for sel in selections)
    lifecycle = lifecycle or {}
    by_stream: dict[str, list[CheckResult]] = defaultdict(list)
    for r in results:
        by_stream[r.stream_id].append(r)

    # Потоки, «оживлённые» UA-fallback'ом (issue #18): последняя успешная
    # проверка прошла с браузерным User-Agent.
    ua_recovered = 0
    for stream_results in by_stream.values():
        for r in sorted(stream_results, key=lambda x: x.checked_at, reverse=True):
            if r.is_success():
                if r.ua_required:
                    ua_recovered += 1
                break

    return {
        "generated_at": generated_at.isoformat(),
        "check_version": __version__,
        "country": country,
        "profile": profile_id,
        "summary": {
            "streams_total": len(selections),
            "streams_included": sum(1 for sel in selections if sel.included),
            "streams_excluded": sum(1 for sel in selections if not sel.included),
            "checks_total": len(results),
            "levels": dict(levels),
            "probe_locations": dict(probe_locations),
            "top_error_codes": dict(error_codes.most_common(10)),
            "lifecycle_stale": sum(1 for lc in lifecycle.values() if lc.stale and not lc.denied),
            "lifecycle_denied": sum(1 for lc in lifecycle.values() if lc.denied),
            "ua_fallback_recovered": ua_recovered,
        },
        "streams": [
            {
                "stream_id": sel.stream.stream_id,
                "channel": sel.channel.name,
                "channel_id": sel.channel.channel_id,
                "source_id": sel.stream.source_id,
                "included": sel.included,
                "score": sel.score.score if sel.score else None,
                "level": sel.score.level.value if sel.score else None,
                "reasons": sel.reasons,
                "consecutive_failures": (
                    lc.consecutive_failures if (lc := lifecycle.get(sel.stream.stream_id)) else 0
                ),
                "uptime_7d_percent": _uptime_percent(
                    by_stream, sel.stream.stream_id, 7, generated_at
                ),
                "uptime_30d_percent": _uptime_percent(
                    by_stream, sel.stream.stream_id, 30, generated_at
                ),
            }
            for sel in selections
        ],
    }


def build_stats(
    *,
    country: str,
    channels_total: int,
    selections: list[SelectedStream],
    results: Iterable[CheckResult],
    generated_at: datetime,
    epg_playlist_channels: int,
    lifecycle: dict[str, StreamLifecycle] | None = None,
) -> dict[str, Any]:
    """Сводные цифры проекта для stats.json и дашборда (issue #9).

    probes_last_check — время последней проверки каждой точки наблюдения:
    главный ранний сигнал «прогон перестал приходить».
    """
    results = list(results)
    lifecycle = lifecycle or {}
    probes: dict[str, str] = {}
    for r in results:
        stamp = r.checked_at.isoformat()
        if r.probe_location not in probes or stamp > probes[r.probe_location]:
            probes[r.probe_location] = stamp
    included = [s for s in selections if s.included]
    error_codes = Counter(r.error_code.value for r in results if r.error_code is not None)
    return {
        "generated_at": generated_at.isoformat(),
        "check_version": __version__,
        "country": country,
        "catalog": {
            "channels": channels_total,
            "streams": len({s.stream.stream_id for s in selections}),
        },
        "playlist": {
            "channels": len({s.channel.channel_id for s in included}),
            "streams": len(included),
        },
        "levels": dict(
            Counter((s.score.level.value if s.score else "no_history") for s in selections)
        ),
        "top_error_codes": dict(error_codes.most_common(10)),
        "lifecycle": {
            "stale": sum(1 for lc in lifecycle.values() if lc.stale and not lc.denied),
            "denied": sum(1 for lc in lifecycle.values() if lc.denied),
        },
        "epg": {
            "playlist_channels": epg_playlist_channels,
            "playlist_total": len(included),
        },
        "probes_last_check": probes,
    }


def render_index_html(
    *,
    site_title: str,
    playlists: list[dict[str, object]],
    report_path: str,
    last_generated: str,
    stats: dict[str, Any] | None = None,
    top_channels: list[dict[str, Any]] | None = None,
) -> str:
    """Статическая страница: счётчики, топ каналов, артефакты (issue #9)."""
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item.get('title') or item.get('filename', '')))}</td>"
        f'<td><a href="{html.escape(str(item.get("url", "")))}">'
        f"{html.escape(str(item.get('filename', '')))}</a></td>"
        f"<td>{item.get('included', '—')}</td>"
        "</tr>"
        for item in playlists
    )

    stats_block = ""
    top_block = ""
    if stats:
        catalog: dict[str, Any] = stats.get("catalog") or {}
        playlist: dict[str, Any] = stats.get("playlist") or {}
        epg: dict[str, Any] = stats.get("epg") or {}
        lifecycle_stats: dict[str, Any] = stats.get("lifecycle") or {}
        probes: dict[str, str] = stats.get("probes_last_check") or {}
        probe_lines = "".join(
            f"<li><code>{html.escape(loc)}</code> — {html.escape(stamp)}</li>"
            for loc, stamp in sorted(probes.items())
        )
        stats_block = f"""
<section class="counters">
  <div><b>{playlist.get("channels", 0)}</b><span>каналов в плейлисте</span></div>
  <div><b>{playlist.get("streams", 0)}</b><span>потоков опубликовано</span></div>
  <div><b>{catalog.get("channels", 0)}</b><span>каналов в каталоге</span></div>
  <div><b>{epg.get("playlist_channels", 0)}/{epg.get("playlist_total", 0)}</b>
       <span>каналов с EPG</span></div>
  <div><b>{lifecycle_stats.get("denied", 0)}</b><span>потоков автодeny</span></div>
</section>
<details>
  <summary>Точки наблюдения: последняя проверка</summary>
  <ul>{probe_lines}</ul>
</details>
"""
        if top_channels:
            top_rows = ""
            for c in top_channels:
                logo = str(c.get("logo") or "")
                logo_cell = (
                    f'<img src="{html.escape(logo)}" alt="" width="24" height="24">' if logo else ""
                )
                top_rows += (
                    "<tr>"
                    f"<td>{logo_cell}</td>"
                    f"<td>{html.escape(str(c.get('name', '')))}</td>"
                    f"<td>{html.escape(str(c.get('group', '')))}</td>"
                    f"<td>{html.escape(str(c.get('score', '—')))}</td>"
                    f"<td>{html.escape(str(c.get('uptime', '—')))}</td>"
                    "</tr>"
                )
            top_block = f"""
<h2>Топ каналов</h2>
<table>
<thead><tr><th></th><th>Канал</th><th>Группа</th><th>Score</th><th>Uptime 7д</th></tr></thead>
<tbody>{top_rows}</tbody>
</table>
"""

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(site_title)}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 56rem;
        padding: 0 1rem; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ text-align: left; padding: .5rem .75rem; border-bottom: 1px solid #ddd; }}
  th {{ vertical-align: middle; }}
  td img {{ vertical-align: middle; border-radius: 4px; }}
  .counters {{ display: flex; flex-wrap: wrap; gap: 1rem; margin: 1.5rem 0; }}
  .counters div {{ display: flex; flex-direction: column; min-width: 9rem;
        background: #f6f8fa; border-radius: 8px; padding: .75rem 1rem; }}
  .counters b {{ font-size: 1.6rem; }}
  .counters span {{ color: #57606a; font-size: .85rem; }}
  footer {{ margin-top: 2rem; color: #666; font-size: .9rem; }}
</style>
</head>
<body>
<h1>{html.escape(site_title)}</h1>
<p>Плейлисты и отчёты генерируются автоматически; каталог — инструмент
мониторинга, а не поставщик телеканалов. Каждый канал прошёл HTTP/HLS-проверку
минимум из двух точек наблюдения.</p>
{stats_block}
<h2>Плейлисты</h2>
<table>
<thead><tr><th>Подборка</th><th>Файл</th><th>Каналов</th></tr></thead>
<tbody>{rows}</tbody>
</table>
{top_block}
<p>
  <a href="{html.escape(report_path)}">report.json</a> ·
  <a href="{html.escape(report_path.replace("report.json", "stats.json"))}">stats.json</a> ·
  <a href="{html.escape(report_path.replace("report.json", "channels.json"))}">channels.json</a> ·
  <a href="{html.escape(report_path.replace("report.json", "streams.json"))}">streams.json</a>
</p>
<footer>Сгенерировано {html.escape(last_generated)} · iptv-ru-monitor {__version__}</footer>
</body>
</html>
"""
