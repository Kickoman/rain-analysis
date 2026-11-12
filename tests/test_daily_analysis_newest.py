#!/usr/bin/env python3
"""Regression test for #456: pick the newest analysis_report.json on a re-run.

run_full_analysis.py writes each run into a timestamped directory
reports/daily/<date>/<Nd>/<YYYYmmdd_HHMMSS>/analysis_report.json. A re-run of
the same date leaves several candidate directories behind; daily_analysis.py
must select the newest one instead of whatever order the filesystem returns.
"""

from pathlib import Path

from daily_analysis import _newest_report


def _matches(*dirnames):
    base = "reports/daily/2026-08-21/7d"
    return [Path(base) / d / "analysis_report.json" for d in dirnames]


def test_picks_newest_when_multiple_runs_exist():
    matches = _matches("20260813_161412", "20260813_184248", "20260813_161437")
    assert _newest_report(matches).parent.name == "20260813_184248"


def test_order_of_input_does_not_matter():
    matches = _matches("20260813_184248", "20260813_161412")
    assert _newest_report(matches).parent.name == "20260813_184248"


def test_single_match_is_unchanged():
    matches = _matches("20260813_161412")
    assert _newest_report(matches).parent.name == "20260813_161412"


def test_later_day_beats_earlier_day_regardless_of_clock_time():
    # A run just after midnight on the 14th is newer than one just before
    # midnight on the 13th, even though "001200" < "235959" lexically.
    matches = _matches("20260813_235959", "20260814_001200")
    assert _newest_report(matches).parent.name == "20260814_001200"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
