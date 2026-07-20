"""Tests for scripts/generate_history_index.py"""

import sys
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from generate_history_index import _extract_best_model, _parse_date_from_filename
from datetime import date


def test_extract_best_model_pressure_variants_colon():
    """F1 with colon format (F1: X.XXX)"""
    html = "<html>Best model: pressure_combined (F1: 0.392)</html>"
    result = _extract_best_model(html)
    assert result == "pressure_combined (F1: 0.392)"


def test_extract_best_model_pressure_variants_equals():
    """F1 with equals format (F1=X.XXX) - issue #130"""
    html = "<html>Best model: pressure_lagged (F1=0.235)</html>"
    result = _extract_best_model(html)
    assert result == "pressure_lagged (F1: 0.235)"


def test_extract_best_model_daily_report():
    """Daily report format with leaderboard table"""
    html = """<html>
    <p>Best overall (F-beta=2.0): combined @ 35%</p>
    <table>
        <tr><td>combined</td><td>0.400</td></tr>
        <tr><td>pressure_combined</td><td>0.392</td></tr>
    </table>
    </html>"""
    result = _extract_best_model(html)
    assert result == "combined (F1: 0.400)"


def test_extract_best_model_no_match():
    """No recognizable format"""
    html = "<html>Some other content</html>"
    result = _extract_best_model(html)
    assert result == "N/A"


def test_parse_date_from_filename_dated():
    """Parse standard dated filename"""
    result = _parse_date_from_filename("2026-07-20.html")
    assert result == (date(2026, 7, 20), True, "2026-07-20.html")


def test_parse_date_from_filename_other():
    """Non-dated filename returns None"""
    result = _parse_date_from_filename("pressure_variants_2026-07-15.html")
    assert result == (None, False, "pressure_variants_2026-07-15.html")


def test_parse_date_from_filename_invalid_date():
    """Invalid date returns None"""
    result = _parse_date_from_filename("2026-13-45.html")
    assert result == (None, False, "2026-13-45.html")


def test_date_sorting_order():
    """Verify that dates sort correctly (newest first)"""
    files = [
        "2026-07-15.html",
        "2026-07-20.html",
        "2026-07-18.html",
        "pressure_variants_2026-07-15.html"
    ]
    
    parsed = [_parse_date_from_filename(f) for f in files]
    dated = [(d, f) for d, is_dated, f in parsed if is_dated]
    dated.sort(key=lambda x: x[0], reverse=True)
    
    expected_order = [
        "2026-07-20.html",
        "2026-07-18.html",
        "2026-07-15.html"
    ]
    
    assert [f for _, f in dated] == expected_order
