import json
from collections import Counter

from xtb_analyzer.filters import filter_instruments
from xtb_analyzer.storage import (
    read_raw,
    read_snapshot,
    write_metadata,
    write_raw,
    write_snapshot,
)


def test_snapshot_round_trip_preserves_values(tmp_path, sample_records):
    original = filter_instruments(sample_records).instruments
    path = write_snapshot(original, tmp_path / "instruments.csv")

    restored = read_snapshot(path)

    assert restored == original
    assert restored[0].long_only is True
    assert isinstance(restored[0].leverage, float)
    assert isinstance(restored[0].precision, int)


def test_snapshot_has_a_header_row(tmp_path, sample_records):
    instruments = filter_instruments(sample_records).instruments
    path = write_snapshot(instruments, tmp_path / "instruments.csv")

    header = path.read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("symbol,description,asset_class")


def test_raw_round_trip(tmp_path, sample_records):
    path = write_raw(sample_records, tmp_path / "raw" / "all_symbols.json")
    assert read_raw(path) == sample_records


def test_metadata_contains_counts(tmp_path):
    path = write_metadata(
        tmp_path / "meta.json",
        source="unit-test",
        total=11,
        kept=3,
        rejections=Counter({"category=FX": 1}),
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["records_returned"] == 11
    assert payload["instruments_kept"] == 3
    assert payload["rejections"] == {"category=FX": 1}
    assert payload["fetched_at"].endswith("+00:00")
