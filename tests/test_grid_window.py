"""
Tests for the analysis window: build_grid() clipping and honest coverage.

Before this, build_grid() spanned the union of every source's timespan. A
43-day Yandex archive alongside 7 days of Home Assistant data produced a
43-day grid that was 84% empty, and coverage was computed against that grid —
so a complete 7-day dataset reported 16% coverage. Combined with a 10-minute
grid carrying hourly ground truth, reported coverage could not exceed 16.7%
however good the data was, and the "low coverage" warning fired permanently.
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

import rainlib as rl
from run_analysis import AnalysisConfig, compute_coverage, source_ranges


BASE = datetime(2026, 7, 1, tzinfo=timezone.utc)


def hourly(n, start=BASE, **cols):
    idx = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({k: v(len(idx)) if callable(v) else [v] * len(idx)
                         for k, v in cols.items()}, index=idx)


def ha_frame(n=24 * 7, start=BASE):
    return hourly(n, start, temp=20.0, rh=60.0, pressure=1010.0)


def om_frame(n=24 * 7, start=BASE):
    return hourly(n, start, om_precip=0.0, om_temp=19.0)


# ---------------------------------------------------------------------------
# Window clipping
# ---------------------------------------------------------------------------

def test_grid_defaults_to_union_of_sources():
    """Unchanged default behaviour: no window means span everything."""
    grid = rl.build_grid(ha_frame(24), om_frame(24 * 10), freq="1h")
    assert grid.index.min() == BASE
    assert grid.index.max() == BASE + timedelta(hours=24 * 10 - 1)


def test_grid_clips_to_requested_window():
    """A long source must not stretch the grid past the requested window."""
    start = BASE + timedelta(days=30)
    end = start + timedelta(days=7)

    grid = rl.build_grid(ha_frame(24 * 7, start), om_frame(24 * 43), freq="1h",
                         start=start, end=end)

    assert grid.index.min() == start
    assert grid.index.max() == end
    assert len(grid) == 24 * 7 + 1


def test_clipping_is_what_makes_coverage_honest():
    """The regression this fixes: 7 days of data inside a 43-day grid."""
    ha = ha_frame(24 * 7)
    yx = hourly(24 * 43, BASE, yx_is_rain=0.0)

    unclipped = rl.build_grid(ha, None, yx, freq="1h")
    clipped = rl.build_grid(ha, None, yx, freq="1h",
                            start=BASE, end=BASE + timedelta(days=7))

    ha_cols = ["temp", "rh", "pressure"]
    unclipped_pct = unclipped[ha_cols].notna().any(axis=1).mean() * 100
    clipped_pct = clipped[ha_cols].notna().any(axis=1).mean() * 100

    assert unclipped_pct < 20        # the old, misleading number
    assert clipped_pct > 95          # the truth


def test_window_may_extend_beyond_available_data():
    """Asking for more than exists yields empty rows, not a silent short grid."""
    grid = rl.build_grid(ha_frame(24), om_frame(24), freq="1h",
                         start=BASE, end=BASE + timedelta(days=7))

    assert grid.index.max() == BASE + timedelta(days=7)
    assert grid["temp"].isna().any()


def test_sources_may_ffill_from_before_the_window():
    """Clipping the grid must not discard a sample just before the start."""
    ha = ha_frame(24, BASE)
    start = BASE + timedelta(hours=12)

    grid = rl.build_grid(ha, om_frame(24, BASE), freq="1h",
                         start=start, end=start + timedelta(hours=6))

    assert grid["temp"].notna().all()


def test_naive_and_string_window_bounds_are_utc():
    naive = rl.build_grid(ha_frame(48), om_frame(48), freq="1h",
                          start=datetime(2026, 7, 1, 6), end=datetime(2026, 7, 1, 12))
    text = rl.build_grid(ha_frame(48), om_frame(48), freq="1h",
                         start="2026-07-01T06:00:00", end="2026-07-01T12:00:00")

    assert naive.index.min() == BASE + timedelta(hours=6)
    assert naive.index.equals(text.index)
    assert naive.index.tz is not None


def test_inverted_window_raises():
    with pytest.raises(ValueError, match="after end"):
        rl.build_grid(ha_frame(24), om_frame(24), freq="1h",
                      start=BASE + timedelta(days=1), end=BASE)


# ---------------------------------------------------------------------------
# Hourly grid
# ---------------------------------------------------------------------------

def test_default_grid_freq_is_hourly():
    """Ground truth is hourly; a finer grid only leaves rows unlabelled."""
    assert AnalysisConfig().grid_freq == "1h"


def test_hourly_grid_labels_every_row():
    """On a 10-minute grid only 1 row in 6 can ever carry hourly truth."""
    ha, om = ha_frame(24), om_frame(24)

    ten_min = rl.build_grid(ha, om, freq="10min", start=BASE, end=BASE + timedelta(hours=23))
    hourly_grid = rl.build_grid(ha, om, freq="1h", start=BASE, end=BASE + timedelta(hours=23))

    assert ten_min["om_precip"].notna().mean() == pytest.approx(1 / 6, abs=0.02)
    assert hourly_grid["om_precip"].notna().all()


def test_precipitation_still_not_forward_filled_on_hourly_grid():
    """The 2026-07-18 fix must survive the frequency change."""
    om = om_frame(6).copy()
    om.loc[om.index[2:4], "om_precip"] = np.nan

    grid = rl.build_grid(ha_frame(6), om, freq="1h", start=BASE, end=BASE + timedelta(hours=5))

    assert grid["om_precip"].isna().sum() == 2


# ---------------------------------------------------------------------------
# Coverage and base rate
# ---------------------------------------------------------------------------

def test_coverage_reports_full_when_data_is_complete():
    ha, om = ha_frame(24 * 7), om_frame(24 * 7)
    grid = rl.build_grid(ha, om, freq="1h", start=BASE, end=BASE + timedelta(days=7) - timedelta(hours=1))

    coverage = compute_coverage(grid, ha)

    assert coverage["ha_coverage_pct"] == pytest.approx(100.0)
    assert coverage["om_coverage_pct"] == pytest.approx(100.0)
    assert coverage["grid_rows"] == 24 * 7


def test_coverage_reflects_a_real_gap():
    ha, om = ha_frame(24), om_frame(24).copy()
    om.loc[om.index[12:], "om_precip"] = np.nan
    grid = rl.build_grid(ha, om, freq="1h", start=BASE, end=BASE + timedelta(hours=23))

    assert compute_coverage(grid, ha)["om_coverage_pct"] == pytest.approx(50.0)


def test_coverage_zero_for_absent_sources():
    ha = ha_frame(24)
    grid = rl.build_grid(ha, om_frame(24), freq="1h", start=BASE, end=BASE + timedelta(hours=23))

    coverage = compute_coverage(grid, ha)
    assert coverage["yx_coverage_pct"] == 0.0
    assert coverage["ms_coverage_pct"] == 0.0


def test_coverage_handles_empty_grid():
    empty = pd.DataFrame(index=pd.DatetimeIndex([], tz="UTC"))
    assert compute_coverage(empty, pd.DataFrame())["ha_coverage_pct"] == 0.0


# ---------------------------------------------------------------------------
# Source ranges
# ---------------------------------------------------------------------------

def test_source_ranges_records_each_span():
    ranges = source_ranges(ha_frame(24), om_frame(48), None, None)

    assert ranges["home_assistant"]["rows"] == 24
    assert ranges["open_meteo"]["rows"] == 48
    assert ranges["yandex"] == {"rows": 0, "first": None, "last": None}


def test_source_ranges_exposes_a_stalled_source():
    """A source stuck in the past is invisible in aggregates but obvious here."""
    fresh = ha_frame(24, BASE + timedelta(days=40))
    stale = om_frame(24, BASE)

    ranges = source_ranges(fresh, stale, None, None)
    assert ranges["open_meteo"]["last"] < ranges["home_assistant"]["first"]
