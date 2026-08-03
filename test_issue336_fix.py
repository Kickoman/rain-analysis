#!/usr/bin/env python3
"""Test that the landing page generator correctly handles failed models and low coverage."""

import sys
import re
from pathlib import Path

# Add scripts_utils to path
sys.path.insert(0, str(Path(__file__).parent / "scripts_utils"))

from generate_landing_page import _extract_report_meta, _format_best_model_string, FAILED_MODELS


def test_extract_coverage():
    """Test coverage extraction from report HTML."""
    sample_html = """
    <h1>Daily Model Analysis — 2026-07-28</h1>
    
    <strong>Ground truth distribution:</strong>
    <p>- Rain hours: 61 (1.6%)<br>
    - Dry hours: 131 (3.4%)<br>
    - Unknown: 3697 (95.1%)</p>
    
    <strong>Best overall (F-beta=2):</strong> trend_dominant @ 7d
    
    <table>
    <tr><td>trend_dominant</td><td>0.188</td><td>0.200</td><td>0.177</td></tr>
    </table>
    """
    
    meta = _extract_report_meta(sample_html)
    
    assert meta["date"] == "2026-07-28"
    assert meta["best_model"] == "trend_dominant"
    assert meta["best_f1"] == "0.188"
    assert meta["rain_hours"] == 61
    assert meta["dry_hours"] == 131
    assert meta["unknown_hours"] == 3697
    assert meta["coverage_pct"] == 5.0  # 1.6 + 3.4
    
    print("✅ Coverage extraction test passed")


def test_warning_for_failed_model():
    """Test that failed models get a warning."""
    meta = {
        "best_model": "trend_dominant",
        "best_f1": "0.188",
        "coverage_pct": 5.0,
    }
    
    result = _format_best_model_string(meta)
    
    assert "trend_dominant (F1: 0.188)" in result
    assert "⚠️ This is a known failed experiment" in result
    assert "⚠️ Low coverage (5.0%) — results may be unreliable" in result
    
    print("✅ Failed model warning test passed")


def test_warning_for_low_coverage_only():
    """Test low coverage warning without failed model."""
    meta = {
        "best_model": "ha_live_replica",
        "best_f1": "0.435",
        "coverage_pct": 8.5,
    }
    
    result = _format_best_model_string(meta)
    
    assert "ha_live_replica (F1: 0.435)" in result
    assert "⚠️ Low coverage (8.5%) — results may be unreliable" in result
    assert "failed experiment" not in result.lower()
    
    print("✅ Low coverage warning test passed")


def test_no_warning_for_good_model():
    """Test that good models with good coverage get no warnings."""
    meta = {
        "best_model": "ha_live_replica",
        "best_f1": "0.435",
        "coverage_pct": 15.0,
    }
    
    result = _format_best_model_string(meta)
    
    assert "ha_live_replica (F1: 0.435)" in result
    assert "⚠️" not in result
    
    print("✅ No warning for good model test passed")


def test_failed_models_list():
    """Verify failed models are properly configured."""
    assert "trend_dominant" in FAILED_MODELS
    print(f"✅ Failed models list contains: {FAILED_MODELS}")


if __name__ == "__main__":
    print("Running Issue #336 fix tests...\n")
    
    test_failed_models_list()
    test_extract_coverage()
    test_warning_for_failed_model()
    test_warning_for_low_coverage_only()
    test_no_warning_for_good_model()
    
    print("\n✅ All tests passed!")
