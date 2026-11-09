"""Сопоставление метаданных: EPG, логотипы, алиасы, мост имён."""

from .aliases import AliasIndex
from .epg import (
    EpgChannelData,
    EpgMatch,
    EpgProgramme,
    match_epg,
    namespace_epg,
    parse_xmltv,
    parse_xmltv_channels,
    parse_xmltv_programmes,
)
from .logos import LogoMatch, match_logos, validate_logo
from .name_bridge import BridgeEntry, NameBridge, parse_channels_csv

__all__ = [
    "AliasIndex",
    "BridgeEntry",
    "EpgChannelData",
    "EpgMatch",
    "EpgProgramme",
    "LogoMatch",
    "NameBridge",
    "match_epg",
    "match_logos",
    "namespace_epg",
    "parse_channels_csv",
    "parse_xmltv",
    "parse_xmltv_channels",
    "parse_xmltv_programmes",
    "validate_logo",
]
