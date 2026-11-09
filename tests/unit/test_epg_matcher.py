"""Тесты сопоставления EPG (tvg-id, алиасы, нормализованные имена)."""

from __future__ import annotations

from iptv_monitor.domain.channel import Channel
from iptv_monitor.domain.enums import MatchMethod
from iptv_monitor.metadata import AliasIndex, match_epg, parse_xmltv
from iptv_monitor.metadata.epg.parser import EpgChannelData
from iptv_monitor.settings import AliasRule


def _channel(name: str, tvg_id: str | None = None, alt: list[str] | None = None) -> Channel:
    return Channel(
        channel_id=f"ru-{name.lower().replace(' ', '-')}",
        name=name,
        country="RU",
        tvg_id=tvg_id,
        alt_names=alt or [],
    )


EPG = [
    EpgChannelData(id="1tv.ru", display_names=["Первый канал", "Первый"]),
    EpgChannelData(id="matchtv.ru", display_names=["Матч ТВ", "Матч!"]),
    EpgChannelData(id="5-tv.ru", display_names=["Пятый канал"]),
]


def test_exact_tvg_id_match() -> None:
    matches = match_epg([_channel("Первый", tvg_id="1tv.ru")], EPG, AliasIndex([]))
    assert len(matches) == 1
    assert matches[0].method == MatchMethod.TVG_ID
    assert matches[0].confidence == 1.0
    assert matches[0].manual is False


def test_manual_alias_wins_over_name() -> None:
    # Без алиаса канал «Первый» сопоставляется по нормализованному имени.
    baseline = match_epg([_channel("Первый")], EPG, AliasIndex([]))
    assert baseline and baseline[0].method == MatchMethod.NORMALIZED_NAME

    # Алиас применим только если его tvg_id есть в EPG (формат id провайдера).
    epg_with_alias = EPG + [EpgChannelData(id="alias-1tv.ru", display_names=["Иное имя"])]
    aliases = AliasIndex([AliasRule(name="Первый", tvg_id="alias-1tv.ru", manual=True)])
    matches = match_epg([_channel("Первый")], epg_with_alias, aliases)
    assert len(matches) == 1
    assert matches[0].method == MatchMethod.ALIAS
    assert matches[0].tvg_id == "alias-1tv.ru"
    assert matches[0].manual is True

    # Если id алиаса в EPG нет — алиас пропускается, работает имя.
    matches_no_id = match_epg([_channel("Первый")], EPG, aliases)
    assert matches_no_id[0].method == MatchMethod.NORMALIZED_NAME


def test_normalized_name_match_with_alt_names() -> None:
    matches = match_epg([_channel("Спорт канал", alt=["Матч ТВ HD"])], EPG, AliasIndex([]))
    assert len(matches) == 1
    assert matches[0].method == MatchMethod.NORMALIZED_NAME
    assert matches[0].tvg_id == "matchtv.ru"


def test_unmatched_channel_has_no_match() -> None:
    matches = match_epg([_channel("Неизвестный канал")], EPG, AliasIndex([]))
    assert matches == []


def test_xmltv_fixture_parses() -> None:
    text = open("tests/fixtures/ru_sample.xmltv", encoding="utf-8").read()
    channels, programmes = parse_xmltv(text)
    assert len(channels) == 3
    assert len(programmes) == 2  # запись с битым временем пропущена
    assert programmes[0].title == "Новости"


# --- issue #22: fuzzy, country-scope алиасов, детерминизм дублей ----------


def _epg(cid: str, *names: str) -> EpgChannelData:
    return EpgChannelData(id=cid, display_names=list(names))


def test_fuzzy_match_above_threshold() -> None:
    """Имя с опечаткой/суффиксом находит EPG-канал методом FUZZY."""
    epg = [_epg("1tv", "Первый канал")]
    matches = match_epg([_channel("Первый канав")], epg, AliasIndex([]), fuzzy_threshold=85.0)
    assert len(matches) == 1
    assert matches[0].method == MatchMethod.FUZZY
    assert matches[0].tvg_id == "1tv"
    assert matches[0].confidence <= 0.65  # ниже моста имён


def test_fuzzy_below_threshold_no_match() -> None:
    epg = [_epg("1tv", "Первый канал")]
    matches = match_epg(
        [_channel("Совершенно другое имя")], epg, AliasIndex([]), fuzzy_threshold=85.0
    )
    assert matches == []


def test_fuzzy_disabled_by_default() -> None:
    """Без fuzzy_threshold (> 0) этап неактивен — старое поведение."""
    epg = [_epg("1tv", "Первый канал")]
    matches = match_epg([_channel("Первый канав")], epg, AliasIndex([]))
    assert matches == []


def test_fuzzy_ambiguous_candidates_skipped() -> None:
    """Два EPG-канала с близким score — неоднозначно, матч не применяется."""
    epg = [
        _epg("sport-a", "Спорт Плюс"),
        _epg("sport-b", "Спорт Плус"),  # почти то же имя
    ]
    ambiguous: list[str] = []
    matches = match_epg(
        [_channel("Спорт Плюсс")],
        epg,
        AliasIndex([]),
        fuzzy_threshold=85.0,
        ambiguous=ambiguous,
    )
    assert matches == []
    assert ambiguous == ["ru-спорт-плюсс"]


def test_duplicate_display_names_deterministic() -> None:
    """Дубли display-name: выбор детерминирован (частота, потом id)."""
    epg = [
        _epg("zzz-dup", "Канал Д", "Канал Д"),
        _epg("aaa-dup", "Канал Д"),
    ]
    matches = match_epg([_channel("Канал Д")], epg, AliasIndex([]))
    assert len(matches) == 1
    # «zzz-dup» ссылается на имя дважды — побеждает по частоте,
    # несмотря на больший id
    assert matches[0].tvg_id == "zzz-dup"


def test_duplicate_display_names_tie_broken_by_id() -> None:
    epg = [
        _epg("bbb-dup", "Канал Д"),
        _epg("aaa-dup", "Канал Д"),
    ]
    matches = match_epg([_channel("Канал Д")], epg, AliasIndex([]))
    assert matches[0].tvg_id == "aaa-dup"


def test_alias_country_scope() -> None:
    """RU-алиас не срабатывает для одноимённого канала другой страны."""
    ru_rule = AliasRule(name="Первый", tvg_id="1tv.ru", country="RU")
    epg = [_epg("1tv.ru", "Первый канал")]
    ua_channel = Channel(
        channel_id="ua-pershyi",
        name="Первый",
        country="UA",
        tvg_id=None,
    )
    matches = match_epg([ua_channel], epg, AliasIndex([ru_rule]))
    assert matches == []
    # а для RU-канала работает
    matches_ru = match_epg([_channel("Первый")], epg, AliasIndex([ru_rule]))
    assert len(matches_ru) == 1
    assert matches_ru[0].method == MatchMethod.ALIAS


def test_alias_global_rule_works_for_any_country() -> None:
    """Правило без страны — глобальное."""
    rule = AliasRule(name="Евроньюс", tvg_id="euronews", country=None)
    epg = [_epg("euronews", "Euronews")]
    matches = match_epg([_channel("Евроньюс")], epg, AliasIndex([rule]))
    assert len(matches) == 1
