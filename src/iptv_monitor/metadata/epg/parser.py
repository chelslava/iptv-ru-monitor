"""Разбор XMLTV (EPG): каналы и программы, декодирование по объявлению.

Крупные источники (iptvx.one — до сотен мегабайт) разбираются в два
прохода iterparse: сначала только каналы, после сопоставления — программы
лишь для сматченных id. Это держит память ограниченной.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from io import StringIO
from pathlib import Path

from pydantic import BaseModel

_XMLTV_TIME_FORMATS = ("%Y%m%d%H%M%S %z", "%Y%m%d%H%M%S")
_ENCODING_RE = re.compile(rb'encoding=["\']([A-Za-z0-9_.-]+)["\']')


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
    # Пробрасываются клиентам, если источник их даёт (issue #26): жанры
    # и подзаголовки программ, иконка эпизода.
    sub_title: str | None = None
    category: str | None = None
    icon: str | None = None


def parse_xmltv_time(value: str) -> datetime:
    """Разобрать время XMLTV ('20260101120000 +0300' и варианты без зоны)."""
    stripped = value.strip()
    for fmt in _XMLTV_TIME_FORMATS:
        try:
            return datetime.strptime(stripped, fmt)
        except ValueError:
            continue
    raise ValueError(f"invalid XMLTV time: {value!r}")


def decode_xmltv(payload: bytes) -> str:
    """Декодировать XMLTV по объявлению; без объявления — utf-8, затем cp1251.

    Многие RU-провайдеры (iptvx.one) отдают файлы в windows-1251 без
    объявления — прямое utf-8-декодирование даёт mojibake и ломает
    сопоставление имён.
    """
    declaration = payload[:200].lstrip()
    if declaration.startswith(b"<?xml"):
        match = _ENCODING_RE.search(declaration)
        if match:
            declared = match.group(1).decode("ascii", errors="replace").lower()
            if declared not in ("utf-8", "utf8"):
                try:
                    return payload.decode(declared)
                except (UnicodeDecodeError, LookupError):
                    pass  # объявленный кодек не сработал — ниже utf-8/cp1251
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload.decode("cp1251", errors="replace")


def _iter_channels(root_stream) -> list[EpgChannelData]:
    channels: list[EpgChannelData] = []
    for _event, element in ET.iterparse(root_stream, events=("end",)):
        if element.tag == "channel":
            channel_id = element.get("id")
            if channel_id:
                names = [
                    (el.text or "").strip() for el in element.findall("display-name") if el.text
                ]
                icon_el = element.find("icon")
                icon_url = icon_el.get("src") if icon_el is not None else None
                channels.append(
                    EpgChannelData(id=channel_id, display_names=names, icon_url=icon_url)
                )
            element.clear()
    return channels


def _programme_fields(element) -> dict[str, object]:
    """Текстовые поля элемента programme (title обязателен, issue #26)."""

    def _text(tag: str) -> str | None:
        el = element.find(tag)
        return (el.text or "").strip() if el is not None and el.text else None

    return {
        "title": _text("title"),
        "description": _text("desc"),
        "sub_title": _text("sub-title"),
        "category": _text("category"),
        "icon": (element.find("icon").get("src") if element.find("icon") is not None else None),
    }


def _iter_programmes(root_stream, channel_ids: set[str] | None) -> list[EpgProgramme]:
    programmes: list[EpgProgramme] = []
    for _event, element in ET.iterparse(root_stream, events=("end",)):
        if element.tag == "programme":
            channel = element.get("channel", "")
            if channel_ids is None or channel in channel_ids:
                try:
                    start = parse_xmltv_time(element.get("start", ""))
                    stop_attr = element.get("stop")
                    stop = parse_xmltv_time(stop_attr) if stop_attr else None
                except ValueError:
                    element.clear()
                    continue
                fields = _programme_fields(element)
                title = fields.get("title")
                if title:
                    programmes.append(
                        EpgProgramme(channel=channel, start=start, stop=stop, **fields)  # type: ignore[arg-type]
                    )
            element.clear()
    return programmes


def _prepare(source: bytes | str | Path):
    if isinstance(source, bytes):
        return StringIO(decode_xmltv(source))
    if isinstance(source, Path):
        return str(source)  # ET.iterparse принимает имя файла
    return StringIO(source)  # str — текст XML


def parse_xmltv_channels(source: bytes | str) -> list[EpgChannelData]:
    """Только каналы XMLTV (первый проход, малая память)."""
    return _iter_channels(_prepare(source))


def parse_xmltv_programmes(
    source: bytes | str,
    channel_ids: set[str] | None = None,
) -> list[EpgProgramme]:
    """Программы XMLTV; channel_ids ограничивает разбор сматченными каналами."""
    return _iter_programmes(_prepare(source), channel_ids)


def parse_xmltv(source: str | Path) -> tuple[list[EpgChannelData], list[EpgProgramme]]:
    """Разобрать XMLTV целиком (совместимость; для больших файлов — два прохода).

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
        fields = _programme_fields(element)
        title = fields.get("title")
        if not title:
            continue
        programmes.append(
            EpgProgramme(channel=element.get("channel", ""), start=start, stop=stop, **fields)  # type: ignore[arg-type]
        )

    return channels, programmes


def namespace_epg(
    source_id: str,
    channels: list[EpgChannelData],
    programmes: list[EpgProgramme],
) -> tuple[list[EpgChannelData], list[EpgProgramme]]:
    """Неймспейсить id источником («epg-pw-ru:7103»).

    id XMLTV уникальны только внутри источника: числовые id двух
    провайдеров сталкиваются, и без неймспейса программы перепутаются.
    Плейлист и XMLTV используют одни и те же неймспейсированные id,
    поэтому согласованность M3U<->XMLTV сохраняется.
    """
    prefix = f"{source_id}:"
    ns_channels = [channel.model_copy(update={"id": prefix + channel.id}) for channel in channels]
    ns_programmes = [
        programme.model_copy(update={"channel": prefix + programme.channel})
        for programme in programmes
    ]
    return ns_channels, ns_programmes
