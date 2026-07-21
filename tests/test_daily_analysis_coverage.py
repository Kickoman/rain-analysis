#!/usr/bin/env python3
"""
Tests for daily_analysis.py data coverage detection (Issue #157).

Ensures that identical datasets across different windows are detected and reported.
"""

import sys
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from daily_analysis_fixed import check_data_overlap


def test_identical_7d_14d_windows():
    """Test detection when 7d and 14d windows share identical data."""
    results_7d = {
        'metadata': {
            'data_stats': {
                'grid_start': '2026-07-01 23:00:00+00:00',
                'grid_end': '2026-07-20 23:00:00+00:00',
                'grid_shape': [2737, 25]
            }
        }
    }
    
    results_14d = {
        'metadata': {
            'data_stats': {
                'grid_start': '2026-07-01 23:00:00+00:00',  # Same as 7d!
                'grid_end': '2026-07-20 23:00:00+00:00',
                'grid_shape': [2737, 25]  # Same shape!
            }
        }
    }
    
    results_28d = {
        'metadata': {
            'data_stats': {
                'grid_start': '2026-06-22 00:00:00+00:00',
                'grid_end': '2026-07-20 23:00:00+00:00',
                'grid_shape': [4171, 25]
            }
        }
    }
    
    windows_data, warnings = check_data_overlap(results_7d, results_14d, results_28d)
    
    # Should detect 7d and 14d overlap
    assert len(warnings) == 1
    assert warnings[0]['windows'] == ['7d', '14d']
    assert warnings[0]['reason'] == 'identical_dataset'
    assert warnings[0]['shape'] == (2737, 25)


def test_all_windows_different():
    """Test when all windows have different data (normal case)."""
    results_7d = {
        'metadata': {
            'data_stats': {
                'grid_start': '2026-07-13 00:00:00+00:00',
                'grid_end': '2026-07-20 23:00:00+00:00',
                'grid_shape': [1152, 25]
            }
        }
    }
    
    results_14d = {
        'metadata': {
            'data_stats': {
                'grid_start': '2026-07-06 00:00:00+00:00',
                'grid_end': '2026-07-20 23:00:00+00:00',
                'grid_shape': [2160, 25]
            }
        }
    }
    
    results_28d = {
        'metadata': {
            'data_stats': {
                'grid_start': '2026-06-22 00:00:00+00:00',
                'grid_end': '2026-07-20 23:00:00+00:00',
                'grid_shape': [4171, 25]
            }
        }
    }
    
    windows_data, warnings = check_data_overlap(results_7d, results_14d, results_28d)
    
    # No overlaps
    assert len(warnings) == 0


def test_identical_14d_28d_windows():
    """Test detection when 14d and 28d windows share identical data."""
    results_7d = {
        'metadata': {
            'data_stats': {
                'grid_start': '2026-07-01 23:00:00+00:00',
                'grid_end': '2026-07-20 23:00:00+00:00',
                'grid_shape': [2737, 25]
            }
        }
    }
    
    results_14d = {
        'metadata': {
            'data_stats': {
                'grid_start': '2026-06-22 00:00:00+00:00',
                'grid_end': '2026-07-20 23:00:00+00:00',
                'grid_shape': [4171, 25]
            }
        }
    }
    
    results_28d = {
        'metadata': {
            'data_stats': {
                'grid_start': '2026-06-22 00:00:00+00:00',  # Same as 14d!
                'grid_end': '2026-07-20 23:00:00+00:00',
                'grid_shape': [4171, 25]  # Same shape!
            }
        }
    }
    
    windows_data, warnings = check_data_overlap(results_7d, results_14d, results_28d)
    
    # Should detect 14d and 28d overlap
    assert len(warnings) == 1
    assert warnings[0]['windows'] == ['14d', '28d']
    assert warnings[0]['reason'] == 'identical_dataset'


def test_windows_data_extraction():
    """Test that windows_data correctly extracts metadata."""
    results_7d = {
        'metadata': {
            'data_stats': {
                'grid_start': '2026-07-13 00:00:00+00:00',
                'grid_end': '2026-07-20 23:00:00+00:00',
                'grid_shape': [1152, 25]
            }
        }
    }
    
    results_14d = {
        'metadata': {
            'data_stats': {
                'grid_start': '2026-07-06 00:00:00+00:00',
                'grid_end': '2026-07-20 23:00:00+00:00',
                'grid_shape': [2160, 25]
            }
        }
    }
    
    results_28d = {
        'metadata': {
            'data_stats': {
                'grid_start': '2026-06-22 00:00:00+00:00',
                'grid_end': '2026-07-20 23:00:00+00:00',
                'grid_shape': [4171, 25]
            }
        }
    }
    
    windows_data, _ = check_data_overlap(results_7d, results_14d, results_28d)
    
    assert windows_data['7d']['start'] == '2026-07-13 00:00:00+00:00'
    assert windows_data['7d']['shape'] == (1152, 25)
    assert windows_data['14d']['start'] == '2026-07-06 00:00:00+00:00'
    assert windows_data['14d']['shape'] == (2160, 25)
    assert windows_data['28d']['start'] == '2026-06-22 00:00:00+00:00'
    assert windows_data['28d']['shape'] == (4171, 25)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
