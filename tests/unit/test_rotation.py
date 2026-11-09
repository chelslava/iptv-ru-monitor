"""Ротация каталога проверок (issues #16, #17)."""

from __future__ import annotations

import pytest

from iptv_monitor.checking.scheduler import apply_rotation
from iptv_monitor.domain.enums import StreamProtocol
from iptv_monitor.domain.stream import Stream, make_stream_id


def _catalog(n: int) -> list[Stream]:
    out = []
    for i in range(n):
        url = f"https://src{i % 3}.example/ch{i}.m3u8"
        out.append(
            Stream(
                stream_id=make_stream_id(url),
                channel_id=f"ru-ch{i}",
                url=url,
                protocol=StreamProtocol.HLS,
                source_id=f"src-{i % 3}",
            )
        )
    return out


def test_stride_slice_disjoint_and_complete() -> None:
    """Срезы по всем offsets не пересекаются и вместе покрывают каталог."""
    catalog = _catalog(101)
    parts = 4
    seen: list[Stream] = []
    for offset in range(parts):
        seen.extend(apply_rotation(catalog, offset, parts))
    assert len(seen) == len(catalog)
    assert {s.stream_id for s in seen} == {s.stream_id for s in catalog}


def test_each_slice_spreads_across_sources() -> None:
    """Срез представлен всеми источниками, а не только «головой» каталога."""
    catalog = _catalog(90)
    slice0 = apply_rotation(catalog, 0, 4)
    source_ids = {s.source_id for s in slice0}
    assert len(source_ids) == 3


def test_deterministic() -> None:
    catalog = _catalog(50)
    assert [s.stream_id for s in apply_rotation(catalog, 2, 7)] == [
        s.stream_id for s in apply_rotation(catalog, 2, 7)
    ]


def test_empty_catalog_ok() -> None:
    assert apply_rotation([], 0, 3) == []


@pytest.mark.parametrize("parts", [1, 0, -2])
def test_invalid_parts(parts: int) -> None:
    with pytest.raises(ValueError, match="rotate_parts"):
        apply_rotation(_catalog(10), 0, parts)


def test_invalid_offset() -> None:
    with pytest.raises(ValueError, match="rotate_offset"):
        apply_rotation(_catalog(10), 5, 4)
    with pytest.raises(ValueError, match="rotate_offset"):
        apply_rotation(_catalog(10), -1, 4)
