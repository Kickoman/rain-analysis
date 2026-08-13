#!/usr/bin/env python3
"""Test suite for generate_history_index.py — history card text.

The card shows "best model (F1: X)". The F1 must come from the leaderboard and
from nowhere else: reports also contain a Temporal Metrics table whose F1 is
measured under a ±3h/±1h tolerance at a per-model tuned threshold, and the old
implementation fell through to it whenever the leaderboard cell was not numeric.
"""

import pytest

from generate_history_index import _extract_best_model
from report_parse import leaderboard_f1


LEADERBOARD_ONLY = """
<h2>Model Performance (7-day window)</h2>
<table>
    <tr><td>ha_live</td><td>0.923</td><td>0.950</td><td>0.897</td></tr>
    <tr><td>tuned</td><td>0.901</td><td>0.920</td><td>0.883</td></tr>
</table>
"""

# Shaped like a real daily report: leaderboard first, Temporal Metrics after.
WITH_TEMPORAL = """
<h1>Daily Model Analysis — 2026-07-20</h1>
<p>Best overall (F-beta=2): ha_live @ 55%</p>

<h2>Model Performance (7-day window)</h2>
<table>
    <tr><th>Model</th><th>F1</th><th>Precision</th><th>Recall</th></tr>
    <tr><td>ha_live</td><td>0.923</td><td>0.950</td><td>0.897</td></tr>
    <tr><td>tuned</td><td>0.901</td><td>0.920</td><td>0.883</td></tr>
</table>

<h2>Temporal Metrics (lead=3h, lag=1h)</h2>
<table>
    <tr><th>Model</th><th>F1</th><th>Precision</th><th>Recall</th></tr>
    <tr><td>ha_live</td><td>0.850</td><td>0.880</td><td>0.822</td></tr>
    <tr><td>tuned</td><td>0.830</td><td>0.860</td><td>0.801</td></tr>
</table>
"""

# The regression: the best model has no scored samples this run.
BEST_MODEL_IS_NA = """
<h1>Daily Model Analysis — 2026-08-13</h1>
<p>Best overall (F-beta=2): ha_live_actual @ 55%</p>

<h2>Model Performance (7-day window)</h2>
<table>
    <tr><th>Model</th><th>F1</th><th>Precision</th><th>Recall</th><th>Status</th></tr>
    <tr><td>ha_live_actual</td><td>N/A</td><td>N/A</td><td>N/A</td><td>no data</td></tr>
    <tr><td>combined</td><td>0.273</td><td>0.375</td><td>0.214</td><td></td></tr>
</table>

<h2>Temporal Metrics (lead=3h, lag=1h)</h2>
<table>
    <tr><th>Model</th><th>F1</th><th>Precision</th><th>Recall</th></tr>
    <tr><td>ha_live_actual</td><td>0.500</td><td>1.000</td><td>0.333</td></tr>
</table>
"""


# ---------------------------------------------------------------------------
# F1 lookup
# ---------------------------------------------------------------------------

def test_reads_f1_from_the_leaderboard():
    assert leaderboard_f1(LEADERBOARD_ONLY, "ha_live") == 0.923
    assert leaderboard_f1(LEADERBOARD_ONLY, "tuned") == 0.901


def test_ignores_the_temporal_metrics_table():
    """0.850 is the same model under a ±3h tolerance — a different measurement."""
    assert leaderboard_f1(WITH_TEMPORAL, "ha_live") == 0.923


def test_na_in_the_leaderboard_does_not_fall_through():
    """The regression this guards: N/A used to yield 0.500 from Temporal Metrics."""
    assert leaderboard_f1(BEST_MODEL_IS_NA, "ha_live_actual") is None
    assert leaderboard_f1(BEST_MODEL_IS_NA, "combined") == 0.273


def test_model_not_present_returns_none():
    assert leaderboard_f1(LEADERBOARD_ONLY, "nonexistent_model") is None


def test_scientific_notation():
    html = """
    <h2>Model Performance</h2>
    <table><tr><td>weird_model</td><td>1.23e-02</td><td>0.050</td><td>0.010</td></tr></table>
    """
    assert leaderboard_f1(html, "weird_model") == pytest.approx(0.0123)


# ---------------------------------------------------------------------------
# Card text
# ---------------------------------------------------------------------------

def test_card_uses_the_leaderboard_score():
    assert _extract_best_model(WITH_TEMPORAL) == "ha_live (F1: 0.923)"


def test_card_says_no_data_rather_than_borrowing_a_number():
    assert _extract_best_model(BEST_MODEL_IS_NA) == "ha_live_actual (F1: no data)"


def test_card_handles_pressure_variants_format():
    html = "<html><body><p>Best model: pressure_combined (F1=0.895)</p></body></html>"
    assert _extract_best_model(html) == "pressure_combined (F1: 0.895)"


def test_card_without_any_leaderboard():
    html = """
    <html><body>
    <p>Best overall: ha_live @ 95.0% threshold</p>
    <p>No leaderboard table present</p>
    </body></html>
    """
    assert _extract_best_model(html) == "ha_live (F1: no data)"


def test_card_na_when_no_best_model():
    assert _extract_best_model("<html><body><p>No analysis performed</p></body></html>") == "N/A"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
