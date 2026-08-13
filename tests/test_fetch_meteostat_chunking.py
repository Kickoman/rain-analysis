"""
Tests for Meteostat range chunking.

The API refuses any single request spanning more than 30 days:
    {"detail": "Tried to request data for 43 days. Maximum is 30."}
Because the pipeline treats a Meteostat failure as non-fatal, an unchunked
long-range request dropped the source entirely without anything in the report
saying so — the 28-day window worked and anything longer silently lost pressure
and the second precipitation opinion.
"""

from unittest.mock import patch

import pytest

import fetch_meteostat as fm


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def test_short_range_is_one_chunk():
    assert list(fm.date_chunks("2026-07-01", "2026-07-10")) == [("2026-07-01", "2026-07-10")]


def test_exactly_at_the_limit_is_one_chunk():
    """30 days inclusive is allowed; splitting it would be a wasted request."""
    chunks = list(fm.date_chunks("2026-07-01", "2026-07-30"))
    assert chunks == [("2026-07-01", "2026-07-30")]


def test_range_over_the_limit_is_split():
    chunks = list(fm.date_chunks("2026-07-01", "2026-08-13"))
    assert chunks == [("2026-07-01", "2026-07-30"), ("2026-07-31", "2026-08-13")]


def test_chunks_are_contiguous_and_within_limit():
    from datetime import datetime, timedelta

    chunks = list(fm.date_chunks("2026-01-01", "2026-06-30"))

    for start, end in chunks:
        span = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days + 1
        assert span <= fm.MAX_DAYS_PER_REQUEST

    for (_, prev_end), (next_start, _) in zip(chunks, chunks[1:]):
        gap = datetime.strptime(next_start, "%Y-%m-%d") - datetime.strptime(prev_end, "%Y-%m-%d")
        assert gap == timedelta(days=1)

    assert chunks[0][0] == "2026-01-01"
    assert chunks[-1][1] == "2026-06-30"


def test_single_day_range():
    assert list(fm.date_chunks("2026-07-01", "2026-07-01")) == [("2026-07-01", "2026-07-01")]


# ---------------------------------------------------------------------------
# Stitching chunks back together
# ---------------------------------------------------------------------------

def _chunk(times, station="26850"):
    return {
        "meta": {"station": {"id": station}},
        "data": [{"time": t, "temp": 15.0, "prcp": 0.0} for t in times],
    }


def test_fetch_data_merges_chunks_in_order():
    responses = [
        _chunk(["2026-07-01 00:00:00", "2026-07-01 01:00:00"]),
        _chunk(["2026-08-01 00:00:00"]),
    ]

    with patch.object(fm, "fetch_chunk", side_effect=responses):
        merged = fm.fetch_data("26850", "2026-07-01", "2026-08-13")

    assert [r["time"] for r in merged["data"]] == [
        "2026-07-01 00:00:00", "2026-07-01 01:00:00", "2026-08-01 00:00:00"
    ]


def test_fetch_data_deduplicates_overlapping_chunks():
    responses = [
        _chunk(["2026-07-01 00:00:00", "2026-07-01 01:00:00"]),
        _chunk(["2026-07-01 01:00:00", "2026-07-01 02:00:00"]),
    ]

    with patch.object(fm, "fetch_chunk", side_effect=responses):
        with patch.object(fm, "date_chunks", return_value=[("a", "b"), ("c", "d")]):
            merged = fm.fetch_data("26850", "2026-07-01", "2026-08-13")

    assert len(merged["data"]) == 3


def test_fetch_data_preserves_metadata():
    with patch.object(fm, "fetch_chunk", return_value=_chunk(["2026-07-01 00:00:00"])):
        merged = fm.fetch_data("26850", "2026-07-01", "2026-07-10")

    assert merged["meta"]["station"]["id"] == "26850"


def test_fetch_data_exits_when_every_chunk_is_empty():
    with patch.object(fm, "fetch_chunk", return_value={"data": []}):
        with pytest.raises(SystemExit):
            fm.fetch_data("26850", "2026-07-01", "2026-07-10")


def test_fetch_data_keeps_partial_results():
    """One empty chunk must not discard the data the others returned."""
    responses = [_chunk(["2026-07-01 00:00:00"]), {"data": []}]

    with patch.object(fm, "fetch_chunk", side_effect=responses):
        with patch.object(fm, "date_chunks", return_value=[("a", "b"), ("c", "d")]):
            merged = fm.fetch_data("26850", "2026-07-01", "2026-08-13")

    assert len(merged["data"]) == 1


def test_merged_output_is_loadable_by_rainlib(tmp_path):
    import json
    import rainlib as rl

    with patch.object(fm, "fetch_chunk", return_value=_chunk(
            ["2026-07-01 00:00:00", "2026-07-01 01:00:00"])):
        merged = fm.fetch_data("26850", "2026-07-01", "2026-07-10")

    path = tmp_path / "ms.json"
    path.write_text(json.dumps(merged))

    df = rl.load_meteostat(str(path))
    assert len(df) == 2
    assert "ms_precip" in df.columns
