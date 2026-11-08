"""EPG/XMLTV: разбор и сопоставление."""

from .matcher import EpgMatch, match_epg
from .parser import EpgChannelData, EpgProgramme, parse_xmltv, parse_xmltv_time

__all__ = [
    "EpgChannelData",
    "EpgMatch",
    "EpgProgramme",
    "match_epg",
    "parse_xmltv",
    "parse_xmltv_time",
]
