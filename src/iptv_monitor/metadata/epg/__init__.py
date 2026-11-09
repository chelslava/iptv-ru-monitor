"""EPG/XMLTV: разбор и сопоставление."""

from .matcher import EpgMatch, match_epg
from .parser import (
    EpgChannelData,
    EpgProgramme,
    namespace_epg,
    parse_xmltv,
    parse_xmltv_channels,
    parse_xmltv_programmes,
    parse_xmltv_time,
)

__all__ = [
    "EpgChannelData",
    "EpgMatch",
    "EpgProgramme",
    "match_epg",
    "namespace_epg",
    "parse_xmltv",
    "parse_xmltv_channels",
    "parse_xmltv_programmes",
    "parse_xmltv_time",
]
