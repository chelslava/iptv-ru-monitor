"""Сопоставление метаданных: EPG, логотипы, алиасы."""

from .aliases import AliasIndex
from .epg import EpgChannelData, EpgMatch, EpgProgramme, match_epg, parse_xmltv
from .logos import LogoMatch, match_logos, validate_logo

__all__ = [
    "AliasIndex",
    "EpgChannelData",
    "EpgMatch",
    "EpgProgramme",
    "LogoMatch",
    "match_epg",
    "match_logos",
    "parse_xmltv",
    "validate_logo",
]
