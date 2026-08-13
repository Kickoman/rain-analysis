#!/usr/bin/env python3
"""Test that the landing page generator correctly warns about failed experiments.

This test addresses issue #336: the landing page should warn users when
a failed experimental model (like trend_dominant) is reported as "best"
due to insufficient ground truth coverage or other data quality issues.
"""

import sys
from pathlib import Path

# Add scripts_utils to path for testing
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts_utils"))

from generate_landing_page import _is_failed_experiment, _extract_report_meta, MODEL_DESCRIPTIONS


def test_is_failed_experiment():
    """Test that failed experiments are correctly identified from MODEL_DESCRIPTIONS."""
    # trend_dominant is marked with ❌ in MODEL_DESCRIPTIONS
    assert _is_failed_experiment("trend_dominant")
    
    # Production models should not be marked as failed
    assert not _is_failed_experiment("ha_live_actual")
    assert not _is_failed_experiment("combined")
    assert not _is_failed_experiment("original")
    
    # Unknown models should not be marked as failed
    assert not _is_failed_experiment("unknown_model")


def test_failed_experiment_marker_in_descriptions():
    """Verify that MODEL_DESCRIPTIONS contains the expected failed experiment marker.
    
    This test ensures the ❌ marker convention is maintained. If this test fails,
    either the marker was removed (breaking _is_failed_experiment logic) or a new
    failed experiment was added without the marker.
    """
    # At least one model should be marked as failed
    failed_models = [
        model for model, desc in MODEL_DESCRIPTIONS.items()
        if desc.startswith("❌")
    ]
    
    assert len(failed_models) >= 1, "No failed experiments found in MODEL_DESCRIPTIONS"
    assert "trend_dominant" in failed_models, "trend_dominant should be marked as failed"


def test_extract_report_meta_basic():
    """Test basic metadata extraction from report HTML."""
    sample_html = """
    <h1>Daily Model Analysis — 2026-07-28</h1>
    
    <strong>Best overall (F-beta=2):</strong> trend_dominant @ 7d
    
    <table>
    <tr><td>trend_dominant</td><td>0.188</td><td>0.200</td><td>0.177</td></tr>
    <tr><td>original</td><td>0.440</td><td>0.450</td><td>0.430</td></tr>
    </table>
    
    <strong>Ground truth sources:</strong>
    Open-Meteo precipitation: 5.0%
    """
    
    meta = _extract_report_meta(sample_html)
    
    assert meta["date"] == "2026-07-28"
    assert meta["best_model"] == "trend_dominant"
    assert meta["best_f1"] == "0.188"
    assert meta["om_coverage"] == 5.0
