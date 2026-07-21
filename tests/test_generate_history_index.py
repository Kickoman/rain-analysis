#!/usr/bin/env python3
"""Test suite for generate_history_index.py — edge cases and F1 extraction logic."""

import sys
from pathlib import Path
import pytest

# Import the module under test
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from generate_history_index import _extract_best_model, _extract_f1_from_leaderboard


def test_extract_f1_from_leaderboard_single_table():
    """Should extract F1 from the first table with matching structure."""
    html = """
    <table>
        <tr><td>ha_live</td><td>0.923</td><td>0.950</td><td>0.897</td></tr>
        <tr><td>tuned</td><td>0.901</td><td>0.920</td><td>0.883</td></tr>
    </table>
    """
    assert _extract_f1_from_leaderboard(html, "ha_live") == 0.923
    assert _extract_f1_from_leaderboard(html, "tuned") == 0.901


def test_extract_f1_from_leaderboard_multiple_tables():
    """Should extract F1 from FIRST table, ignore later duplicates."""
    html = """
    <h2>Overall Leaderboard</h2>
    <table>
        <tr><td>ha_live</td><td>0.923</td><td>0.950</td><td>0.897</td></tr>
        <tr><td>tuned</td><td>0.901</td><td>0.920</td><td>0.883</td></tr>
    </table>
    
    <h3>7-day Window Results</h3>
    <table>
        <tr><td>ha_live</td><td>0.850</td><td>0.880</td><td>0.822</td></tr>
        <tr><td>tuned</td><td>0.830</td><td>0.860</td><td>0.801</td></tr>
    </table>
    
    <h3>14-day Window Results</h3>
    <table>
        <tr><td>ha_live</td><td>0.910</td><td>0.935</td><td>0.886</td></tr>
        <tr><td>tuned</td><td>0.895</td><td>0.915</td><td>0.876</td></tr>
    </table>
    """
    # Should match the first table (0.923), not the 7d (0.850) or 14d (0.910)
    assert _extract_f1_from_leaderboard(html, "ha_live") == 0.923
    assert _extract_f1_from_leaderboard(html, "tuned") == 0.901


def test_extract_f1_from_leaderboard_model_not_found():
    """Should return None if model is not in any table."""
    html = """
    <table>
        <tr><td>ha_live</td><td>0.923</td><td>0.950</td><td>0.897</td></tr>
    </table>
    """
    assert _extract_f1_from_leaderboard(html, "nonexistent_model") is None


def test_extract_f1_from_leaderboard_scientific_notation():
    """Should handle scientific notation in F1 values."""
    html = """
    <table>
        <tr><td>weird_model</td><td>1.23e-02</td><td>0.050</td><td>0.010</td></tr>
    </table>
    """
    result = _extract_f1_from_leaderboard(html, "weird_model")
    assert result is not None
    assert abs(result - 0.0123) < 1e-6


def test_extract_best_model_daily_format_with_multiple_tables():
    """Full integration: extract best model from realistic multi-table daily report."""
    html = """
    <html>
    <body>
    <h1>Daily Model Analysis — 2026-07-20</h1>
    <p>Best overall (F-beta=1): ha_live @ 95.0% threshold</p>
    
    <h2>Overall Leaderboard</h2>
    <table>
        <tr><th>Model</th><th>F1</th><th>Precision</th><th>Recall</th></tr>
        <tr><td>ha_live</td><td>0.923</td><td>0.950</td><td>0.897</td></tr>
        <tr><td>tuned</td><td>0.901</td><td>0.920</td><td>0.883</td></tr>
        <tr><td>original</td><td>0.875</td><td>0.890</td><td>0.861</td></tr>
    </table>
    
    <h3>7-day Window Results</h3>
    <table>
        <tr><th>Model</th><th>F1</th><th>Precision</th><th>Recall</th></tr>
        <tr><td>ha_live</td><td>0.850</td><td>0.880</td><td>0.822</td></tr>
        <tr><td>tuned</td><td>0.830</td><td>0.860</td><td>0.801</td></tr>
    </table>
    
    <h3>14-day Window Results</h3>
    <table>
        <tr><th>Model</th><th>F1</th><th>Precision</th><th>Recall</th></tr>
        <tr><td>ha_live</td><td>0.910</td><td>0.935</td><td>0.886</td></tr>
        <tr><td>tuned</td><td>0.895</td><td>0.915</td><td>0.876</td></tr>
    </table>
    </body>
    </html>
    """
    result = _extract_best_model(html)
    # Should extract "ha_live (F1: 0.923)" from the FIRST table, not 0.850 or 0.910
    assert result == "ha_live (F1: 0.923)"


def test_extract_best_model_pressure_variants_format():
    """Should handle pressure variants format: 'Best model: name (F1=X.XXX)'."""
    html = "<html><body><p>Best model: pressure_combined (F1=0.895)</p></body></html>"
    assert _extract_best_model(html) == "pressure_combined (F1: 0.895)"


def test_extract_best_model_no_f1_available():
    """Should return model name without F1 if table extraction fails."""
    html = """
    <html>
    <body>
    <p>Best overall: ha_live @ 95.0% threshold</p>
    <p>No leaderboard table present</p>
    </body>
    </html>
    """
    assert _extract_best_model(html) == "ha_live"


def test_extract_best_model_na_fallback():
    """Should return 'N/A' if no best model can be identified."""
    html = "<html><body><p>No analysis performed</p></body></html>"
    assert _extract_best_model(html) == "N/A"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
