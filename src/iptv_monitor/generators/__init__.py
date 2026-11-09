"""Генераторы публичных артефактов: M3U, XMLTV, JSON, отчёты."""

from .json_catalog import channels_catalog, streams_catalog, write_json
from .m3u import M3UEntry, assign_channel_numbers, entry_for, render_m3u
from .report import build_report, build_stats, render_index_html
from .xmltv import render_xmltv

__all__ = [
    "M3UEntry",
    "assign_channel_numbers",
    "build_report",
    "build_stats",
    "channels_catalog",
    "entry_for",
    "render_index_html",
    "render_m3u",
    "render_xmltv",
    "streams_catalog",
    "write_json",
]
