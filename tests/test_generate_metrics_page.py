"""Tests for generate_metrics_page.py source table parsing."""
import sys
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from generate_metrics_page import _extract_source_rows


def test_extract_source_rows_with_descriptions():
    """Test that source rows with descriptions like 'OM (Open-Meteo)' are parsed correctly."""
    html = """
    <table>
        <thead>
            <tr>
                <th>Source</th>
                <th>Rain Hours</th>
                <th>Agreement</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>OM (Open-Meteo)</td>
                <td>42</td>
                <td>95%</td>
            </tr>
            <tr>
                <td>MS (Meteostat)</td>
                <td>38</td>
                <td>90%</td>
            </tr>
            <tr>
                <td>YX</td>
                <td>45</td>
                <td>100%</td>
            </tr>
        </tbody>
    </table>
    """
    
    rows = _extract_source_rows(html)
    
    assert len(rows) == 3, f"Expected 3 rows, got {len(rows)}"
    
    assert rows[0]["source"] == "OM"
    assert rows[0]["rain_hours"] == 42
    assert rows[0]["agreement"] == "95%"
    
    assert rows[1]["source"] == "MS"
    assert rows[1]["rain_hours"] == 38
    assert rows[1]["agreement"] == "90%"
    
    assert rows[2]["source"] == "YX"
    assert rows[2]["rain_hours"] == 45
    assert rows[2]["agreement"] == "100%"


def test_extract_source_rows_without_descriptions():
    """Test that simple source codes without descriptions still work."""
    html = """
    <table>
        <tr>
            <td>OM</td>
            <td>42</td>
            <td>95%</td>
        </tr>
        <tr>
            <td>MS</td>
            <td>38</td>
            <td>90%</td>
        </tr>
    </table>
    """
    
    rows = _extract_source_rows(html)
    
    assert len(rows) == 2
    assert rows[0]["source"] == "OM"
    assert rows[0]["rain_hours"] == 42
    assert rows[1]["source"] == "MS"
    assert rows[1]["rain_hours"] == 38


def test_extract_source_rows_skips_header():
    """Test that header row with 'Source' is skipped."""
    html = """
    <table>
        <tr>
            <td>Source</td>
            <td>Rain Hours</td>
            <td>Agreement</td>
        </tr>
        <tr>
            <td>OM (Open-Meteo)</td>
            <td>42</td>
            <td>95%</td>
        </tr>
    </table>
    """
    
    rows = _extract_source_rows(html)
    
    assert len(rows) == 1
    assert rows[0]["source"] == "OM"


def test_extract_source_rows_empty():
    """Test that empty or malformed HTML returns empty list."""
    assert _extract_source_rows("") == []
    assert _extract_source_rows("<table></table>") == []
    assert _extract_source_rows("<p>No table here</p>") == []


if __name__ == "__main__":
    test_extract_source_rows_with_descriptions()
    test_extract_source_rows_without_descriptions()
    test_extract_source_rows_skips_header()
    test_extract_source_rows_empty()
    print("✅ All tests passed")
