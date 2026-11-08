"""Разбор XMLTV (EPG)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

_XMLTV_TIME_FORMATS = ("%Y%m%d%H%M%S %z", "%Y%m%d%H%M%S")


class EpgChannelData(BaseModel):
    """Канал из XMLTV со списком названий и логотипом."""

    id: str
    display_names: list[str]
    icon_url: str | None = None


class EpgProgramme(BaseModel):
    """Программа передач, привязанная к id канала XMLTV."""

    channel: str
    start: datetime
    stop: datetime | None = None
    title: str
    description: str | None = None


def parse_xmltv_time(value: str) -> datetime:
    """Разобрать время XMLTV ('20260101120000 +0300' и варианты без зоны)."""
    stripped = value.strip()
    for fmt in _XMLTV_TIME_FORMATS:
        try:
            return datetime.strptime(stripped, fmt)
        except ValueError:
            continue
    raise ValueError(f"invalid XMLTV time: {value!r}")


def parse_xmltv(source: str | Path) -> tuple[list[EpgChannelData], list[EpgProgramme]]:
    """Разобрать XMLTV из строки или файла.

    Возвращает каналы и программы. Битые элементы пропускаются.
    """
    if isinstance(source, Path):
        root = ET.parse(source).getroot()
    else:
        root = ET.fromstring(source)

    channels: list[EpgChannelData] = []
    for element in root.findall("channel"):
        channel_id = element.get("id")
        if not channel_id:
            continue
        names = [(el.text or "").strip() for el in element.findall("display-name") if el.text]
        icon_el = element.find("icon")
        icon_url = icon_el.get("src") if icon_el is not None else None
        channels.append(EpgChannelData(id=channel_id, display_names=names, icon_url=icon_url))

    programmes: list[EpgProgramme] = []
    for element in root.findall("programme"):
        try:
            start = parse_xmltv_time(element.get("start", ""))
            stop_attr = element.get("stop")
            stop = parse_xmltv_time(stop_attr) if stop_attr else None
        except ValueError:
            continue
        title_el = element.find("title")
        title = (title_el.text or "").strip() if title_el is not None else ""
        if not title:
            continue
        desc_el = element.find("desc")
        programmes.append(
            EpgProgramme(
                channel=element.get("channel", ""),
                start=start,
                stop=stop,
                title=title,
                description=(desc_el.text or "").strip() if desc_el is not None else None,
            )
        )

    return channels, programmes
