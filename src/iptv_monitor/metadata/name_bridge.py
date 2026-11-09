"""Мост имён: канонические имена и алиасы из iptv-org/database (Unlicense).

Каналы каталога наследуют tvg_id формата iptv-org («ChannelOne.ru@SD»).
База database раскрывает этот id в каноническое имя и alt_names (в том
числе русские), что позволяет сопоставить канал с EPG-провайдерами, у
которых display-name на другом языке (epg.pw: «Первый канал» против
унаследованного «Channel One»).

Схема channels.csv: id,name,alt_names,network,owners,country,... —
alt_names перечисляются через «;», имя может содержать запятые (кавычки).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field


@dataclass
class BridgeEntry:
    """Запись базы каналов iptv-org."""

    db_id: str
    name: str
    alt_names: list[str] = field(default_factory=list)

    @property
    def names(self) -> list[str]:
        """Все имена записи: каноническое + алиасы, без пустых."""
        return [self.name, *filter(None, (a.strip() for a in self.alt_names))]


class NameBridge:
    """Индекс базы каналов: id iptv-org -> набор имён."""

    def __init__(self, entries: dict[str, BridgeEntry]) -> None:
        self._entries = entries

    def __len__(self) -> int:
        return len(self._entries)

    def names_for(self, tvg_id: str | None) -> list[str]:
        """Имена для tvg-id канала; «ChannelOne.ru@SD» -> запись «ChannelOne.ru».

        Для id, которых нет в базе (числовые id epg.pw и т.п.), — пустой
        список: мост применяется только к унаследованным iptv-org id.
        """
        if not tvg_id:
            return []
        base = tvg_id.split("@", 1)[0]
        entry = self._entries.get(base)
        return entry.names if entry else []


def parse_channels_csv(text: str) -> NameBridge:
    """Разобрать channels.csv iptv-org/database в NameBridge."""
    reader = csv.DictReader(io.StringIO(text))
    entries: dict[str, BridgeEntry] = {}
    for row in reader:
        db_id = (row.get("id") or "").strip()
        name = (row.get("name") or "").strip()
        if not db_id or not name:
            continue
        alt = [a.strip() for a in (row.get("alt_names") or "").split(";")]
        entries[db_id] = BridgeEntry(db_id=db_id, name=name, alt_names=alt)
    return NameBridge(entries)
