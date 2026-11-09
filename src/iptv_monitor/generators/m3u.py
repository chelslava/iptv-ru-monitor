"""Генерация M3U-плейлистов для TiviMate и других IPTV-плееров."""

from __future__ import annotations

import hashlib
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
    tvg_chno: int | None = None


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


def assign_channel_numbers(
    entries: list[M3UEntry],
    *,
    overrides: dict[str, int] | None = None,
    max_number: int = 9999,
) -> None:
    """Назначить стабильные tvg-chno (issue #7), мутируя entries.

    Номер канала не должен «прыгать» при добавлении/удалении чужих каналов,
    поэтому номер — детерминированный hash от tvg_id (fallback: имя), а не
    порядковый индекс. Коллизии разрешаются линейным проходом по отсортированному
    набору (порядок обработки фиксирован: group_title → name → tvg_id), поэтому
    нумерация воспроизводима между билдами.

    Ручные overrides применяются первыми и резервируют свои номера; ключ
    сопоставляется с именем канала по нормализованной подстроке (имена
    каталога несут суффиксы качества: «Первый канал (1080p)»).
    """
    from ..normalization.channel_names import normalize_name

    taken: set[int] = set()

    def apply_override(entry: M3UEntry, number: int) -> bool:
        if not 1 <= number <= max_number or number in taken:
            return False
        entry.tvg_chno = number
        taken.add(number)
        return True

    if overrides:
        for entry in entries:
            normalized = normalize_name(entry.name)
            for key, number in overrides.items():
                if normalize_name(key) in normalized and apply_override(entry, number):
                    break

    pending = [e for e in entries if e.tvg_chno is None]
    pending.sort(key=lambda e: (e.group_title or "", e.name, e.tvg_id or ""))
    for entry in pending:
        key = entry.tvg_id or entry.name
        digest = int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16)
        number = digest % max_number + 1
        while number in taken:
            number = number % max_number + 1
        entry.tvg_chno = number
        taken.add(number)


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
        if entry.tvg_chno is not None:
            attrs += f' tvg-chno="{entry.tvg_chno}"'
        if entry.tvg_logo:
            attrs += f' tvg-logo="{_escape(entry.tvg_logo)}"'
        if entry.group_title:
            attrs += f' group-title="{_escape(entry.group_title)}"'
        lines.append(f"#EXTINF:-1{attrs},{_escape(entry.name)}")
        lines.append(entry.url)
    lines.append("")  # завершающий перевод строки
    return "\n".join(lines)
