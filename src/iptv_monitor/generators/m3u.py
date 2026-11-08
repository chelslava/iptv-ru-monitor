"""Генерация M3U-плейлистов для TiviMate и других IPTV-плееров."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.channel import Channel
from ..domain.stream import Stream


@dataclass
class M3UEntry:
    """Запись плейлиста с атрибутами tvg-*."""

    name: str
    url: str
    tvg_id: str | None = None
    tvg_name: str | None = None
    tvg_logo: str | None = None
    group_title: str | None = None


def _escape(value: str) -> str:
    """Экранирование значений атрибутов M3U (без двойных кавычек внутри)."""
    return value.replace('"', "'").replace("\n", " ").strip()


def entry_for(channel: Channel, stream: Stream, *, group_title: str | None = None) -> M3UEntry:
    """Построить запись плейлиста из канала и потока.

    M3U и XMLTV используют согласованные ID: tvg_id совпадает с id канала
    в XMLTV (см. generators/xmltv.py).
    """
    return M3UEntry(
        name=channel.name,
        url=stream.url,
        tvg_id=channel.tvg_id,
        tvg_name=channel.name,
        tvg_logo=channel.logo_url,
        group_title=group_title or channel.category.value,
    )


def render_m3u(entries: list[M3UEntry], *, epg_url: str | None = None) -> str:
    """Собрать текст M3U-плейлиста."""
    header = "#EXTM3U"
    if epg_url:
        header += f' url-tvg="{_escape(epg_url)}"'
    lines = [header]
    for entry in entries:
        attrs = ""
        if entry.tvg_id:
            attrs += f' tvg-id="{_escape(entry.tvg_id)}"'
        if entry.tvg_name:
            attrs += f' tvg-name="{_escape(entry.tvg_name)}"'
        if entry.tvg_logo:
            attrs += f' tvg-logo="{_escape(entry.tvg_logo)}"'
        if entry.group_title:
            attrs += f' group-title="{_escape(entry.group_title)}"'
        lines.append(f"#EXTINF:-1{attrs},{_escape(entry.name)}")
        lines.append(entry.url)
    lines.append("")  # завершающий перевод строки
    return "\n".join(lines)
