#!/usr/bin/env python3
"""
Tests for daily_analysis.py output format.

Validates that generated Markdown tables match the format expected by:
- scripts/generate_history_index.py
- scripts/generate_metrics_page.py

These parsers use regex patterns to extract model performance data.
"""

import re
import sys
from pathlib import Path

# Add scripts directory to path for importing
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from daily_analysis import generate_report

# Mock analysis results for testing
MOCK_RESULTS = {
    'scoring': {
        'scores': {
            'ha_live': {
                'f1': 0.456,
                'precision': 0.678,
                'recall': 0.789
            },
            'pressure_gradient': {
                'f1': 0.512,
                'precision': 0.712,
                'recall': 0.823
            }
        },
        'fbeta_recommendations': {
            'ha_live': {
                'beta_2.0': {
                    'fbeta': 0.623,
                    'precision': 0.678,
                    'recall': 0.789
                },
                'beta_3.0': {
                    'fbeta': 0.687,
                    'precision': 0.678,
                    'recall': 0.789
                }
            },
            'pressure_gradient': {
                'beta_2.0': {
                    'fbeta': 0.734,
                    'precision': 0.712,
                    'recall': 0.823
                },
                'beta_3.0': {
                    'fbeta': 0.789,
                    'precision': 0.712,
                    'recall': 0.823
                }
            }
        }
    },
    'cross_check': {
        'precip_comparison': {
            'om_rain_hours': 15,
            'ms_rain_hours': 14,
            'yx_rain_hours': 18,
            'om_ms_agree': 12,
            'om_yx_agree': 13,
            'ms_yx_agree': 11
        },
        'yandex_vs_truth': {
            'yandex_rain_hours': 18,
            'actual_rain_hours': 16,
            'agreement_hours': 14,
            'yandex_only': 4,
            'actual_only': 2
        }
    },
    'metadata': {
        'data_stats': {
            'grid_shape': [1008, 10],  # 7 days * 144 (10-min intervals)
            'ground_truth': {
                'total_rain_hours': 16
            }
        }
    }
}


def test_github_pages_table_format():
    """Test that Model Performance table matches GitHub Pages parser regex."""
    
    report = generate_report("2026-07-20", MOCK_RESULTS, MOCK_RESULTS, MOCK_RESULTS)
    
    # Parser expects: | Model | F1 | Precision | Recall | ... |
    # Regex from generate_history_index.py and generate_metrics_page.py:
    # r'\|\s*(\S+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|'
    
    pattern = r'\|\s*(\S+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|'
    
    # Find the Model Performance (7-day window) section
    lines = report.split('\n')
    in_perf_section = False
    table_found = False
    models_found = []
    
    for line in lines:
        if 'Model Performance (7-day window)' in line:
            in_perf_section = True
            continue
        
        if in_perf_section and line.startswith('##'):
            # Hit next section
            break
        
        if in_perf_section and '|' in line and not line.startswith('|---'):
            # Skip header row
            if 'Model' in line and 'F1' in line:
                table_found = True
                continue
            
            # Try to match data row
            match = re.search(pattern, line)
            if match:
                model, f1, prec, rec = match.groups()
                models_found.append({
                    'model': model,
                    'f1': float(f1),
                    'precision': float(prec),
                    'recall': float(rec)
                })
    
    assert table_found, "Model Performance table not found in report"
    assert len(models_found) >= 2, f"Expected at least 2 models, found {len(models_found)}"
    
    # Verify values match mock data
    ha_live_entry = next((m for m in models_found if m['model'] == 'ha_live'), None)
    assert ha_live_entry is not None, "ha_live model not found in table"
    assert abs(ha_live_entry['f1'] - 0.456) < 0.001
    assert abs(ha_live_entry['precision'] - 0.678) < 0.001
    assert abs(ha_live_entry['recall'] - 0.789) < 0.001
    
    print("✓ GitHub Pages table format valid")


def test_precipitation_source_table():
    """Test that Precipitation Source Reliability table exists."""
    
    report = generate_report("2026-07-20", MOCK_RESULTS, MOCK_RESULTS, MOCK_RESULTS)
    
    assert "## Precipitation Source Reliability" in report
    assert "| Source | Rain Hours |" in report
    assert "OM (Open-Meteo)" in report
    assert "MS (Meteostat)" in report
    assert "YX (Yandex)" in report
    
    # Check that values from mock appear
    assert "15" in report  # om_rain_hours
    assert "14" in report  # ms_rain_hours
    assert "18" in report  # yx_rain_hours
    
    print("✓ Precipitation Source Reliability table present")


def test_multi_window_tables():
    """Test that multi-window comparison tables exist."""
    
    report = generate_report("2026-07-20", MOCK_RESULTS, MOCK_RESULTS, MOCK_RESULTS)
    
    assert "## Multi-Window Comparison" in report
    assert "### F-beta=2 Scores" in report
    assert "| Model | 7d | 14d | 28d | Trend |" in report
    
    assert "### Precision by Window" in report
    assert "### Recall by Window" in report
    
    # Check for trend indicators
    assert any(emoji in report for emoji in ["📈", "📉", "➡️"])
    
    print("✓ Multi-window comparison tables present")


def test_model_rankings():
    """Test that model ranking tables exist."""
    
    report = generate_report("2026-07-20", MOCK_RESULTS, MOCK_RESULTS, MOCK_RESULTS)
    
    assert "## Model Rankings" in report
    assert "### By F-beta=2" in report
    assert "### By F-beta=3" in report
    assert "### By Precision" in report
    
    # Check for ranking structure
    assert "| Rank |" in report
    
    print("✓ Model ranking tables present")


def test_executive_summary():
    """Test that executive summary contains key info."""
    
    report = generate_report("2026-07-20", MOCK_RESULTS, MOCK_RESULTS, MOCK_RESULTS)
    
    assert "## Executive Summary" in report
    assert "Best overall (F-beta=2):" in report
    assert "Key findings:" in report
    
    # Should identify best model
    assert "pressure_gradient" in report  # This has higher F-beta=2 in mock
    
    print("✓ Executive summary present")


def test_key_observations():
    """Test that Key Observations section exists."""
    
    report = generate_report("2026-07-20", MOCK_RESULTS, MOCK_RESULTS, MOCK_RESULTS)
    
    assert "## Key Observations & Recommendations" in report
    assert "Next steps:" in report
    
    print("✓ Key observations section present")


def test_report_header():
    """Test report header format."""
    
    report = generate_report("2026-07-20", MOCK_RESULTS, MOCK_RESULTS, MOCK_RESULTS)
    
    # Should start with title
    assert report.startswith("# Daily Model Analysis — 2026-07-20")
    
    # Should contain metadata
    assert "Generated:" in report
    assert "Analysis windows:" in report
    assert "7-day (recent)" in report
    
    print("✓ Report header format valid")


def test_report_footer():
    """Test report footer."""
    
    report = generate_report("2026-07-20", MOCK_RESULTS, MOCK_RESULTS, MOCK_RESULTS)
    
    assert "_Report generated by daily_analysis.py" in report
    
    print("✓ Report footer present")


if __name__ == "__main__":
    print("Testing daily_analysis.py output format...")
    print("=" * 70)
    
    test_report_header()
    test_executive_summary()
    test_github_pages_table_format()
    test_multi_window_tables()
    test_model_rankings()
    test_precipitation_source_table()
    test_key_observations()
    test_report_footer()
    
    print("=" * 70)
    print("✓ All format tests passed")
