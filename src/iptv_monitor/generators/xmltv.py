"""Генерация XMLTV (EPG) из сопоставленных источников."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import datetime

from .. import __version__
from ..domain.channel import Channel
from ..metadata.epg.parser import EpgProgramme


def _xmltv_time(value: datetime) -> str:
    return f"{value:%Y%m%d%H%M%S %z}"


def render_xmltv(
    channels: Iterable[Channel],
    programmes: Iterable[EpgProgramme],
) -> str:
    """Собрать XMLTV для каналов с tvg_id.

    ID каналов XMLTV согласованы с tvg-id в M3U (см. generators/m3u.py).
    """
    channel_list = [c for c in channels if c.tvg_id]
    known_ids = {c.tvg_id for c in channel_list}

    root = ET.Element("tv", {"generator-info-name": f"iptv-ru-monitor/{__version__}"})
    for channel in channel_list:
        channel_el = ET.SubElement(root, "channel", {"id": channel.tvg_id or ""})
        name_el = ET.SubElement(channel_el, "display-name")
        name_el.text = channel.name
        for alt in channel.alt_names:
            alt_el = ET.SubElement(channel_el, "display-name")
            alt_el.text = alt
        if channel.logo_url:
            ET.SubElement(channel_el, "icon", {"src": channel.logo_url})

    included = 0
    for programme in programmes:
        if programme.channel not in known_ids:
            continue
        attrs = {"channel": programme.channel, "start": _xmltv_time(programme.start)}
        if programme.stop:
            attrs["stop"] = _xmltv_time(programme.stop)
        programme_el = ET.SubElement(root, "programme", attrs)
        title_el = ET.SubElement(programme_el, "title")
        title_el.text = programme.title
        if programme.sub_title:
            sub_el = ET.SubElement(programme_el, "sub-title")
            sub_el.text = programme.sub_title
        if programme.description:
            desc_el = ET.SubElement(programme_el, "desc")
            desc_el.text = programme.description
        if programme.category:
            cat_el = ET.SubElement(programme_el, "category")
            cat_el.text = programme.category
        if programme.icon:
            ET.SubElement(programme_el, "icon", {"src": programme.icon})
        included += 1

    # XMLTV DTD не описывает служебных элементов — счётчик программ виден
    # в report.json/stats.json, а не в XML (issue #26).
    return ET.tostring(root, encoding="unicode", xml_declaration=True)
