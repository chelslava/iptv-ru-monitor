"""Машинно-читаемый отчёт проверок и статическая index-страница."""

from __future__ import annotations

import html
from collections import Counter
from collections.abc import Iterable
from datetime import datetime

from .. import __version__
from ..domain.check_result import CheckResult
from ..filtering import SelectedStream


def build_report(
    *,
    country: str,
    profile_id: str,
    selections: list[SelectedStream],
    results: Iterable[CheckResult],
    generated_at: datetime,
) -> dict[str, object]:
    """Отчёт, объясняющий, почему поток включён или исключён."""
    results = list(results)
    error_codes = Counter(r.error_code.value for r in results if r.error_code is not None)
    probe_locations = Counter(r.probe_location for r in results)
    levels = Counter((sel.score.level.value if sel.score else "no_history") for sel in selections)

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
            }
            for sel in selections
        ],
    }


def render_index_html(
    *,
    site_title: str,
    playlists: list[dict[str, object]],
    report_path: str,
    last_generated: str,
) -> str:
    """Минимальная статическая страница со ссылками на артефакты."""
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item.get('title') or item.get('filename', '')))}</td>"
        f'<td><a href="{html.escape(str(item.get("url", "")))}">'
        f"{html.escape(str(item.get('filename', '')))}</a></td>"
        f"<td>{item.get('included', '—')}</td>"
        "</tr>"
        for item in playlists
    )
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(site_title)}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 48rem;
        padding: 0 1rem; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ text-align: left; padding: .5rem .75rem; border-bottom: 1px solid #ddd; }}
  footer {{ margin-top: 2rem; color: #666; font-size: .9rem; }}
</style>
</head>
<body>
<h1>{html.escape(site_title)}</h1>
<p>Плейлисты и отчёты генерируются автоматически; каталог — инструмент
мониторинга, а не поставщик телеканалов.</p>
<table>
<thead><tr><th>Подборка</th><th>Файл</th><th>Каналов</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<p><a href="{html.escape(report_path)}">Машинно-читаемый отчёт (report.json)</a></p>
<footer>Сгенерировано {html.escape(last_generated)} · iptv-ru-monitor {__version__}</footer>
</body>
</html>
"""
