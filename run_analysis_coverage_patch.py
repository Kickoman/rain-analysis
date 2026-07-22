#!/usr/bin/env python3
"""
Patch to add coverage statistics to load_data() function.
This will be applied to run_analysis.py line 135-169.
"""

NEW_STATS_SECTION = '''
    # Coverage statistics for transparency in reports
    grid_len = len(grid)
    coverage = {}
    
    # HA coverage: any non-NaN value across HA columns
    ha_cols = [c for c in grid.columns if c.startswith(('temp', 'rh', 'pressure')) and c in ha.columns]
    if ha_cols:
        coverage["ha_coverage_pct"] = float((grid[ha_cols].notna().any(axis=1).sum() / grid_len) * 100)
    else:
        coverage["ha_coverage_pct"] = 0.0
    
    # Open-Meteo coverage
    if "om_precip" in grid.columns:
        coverage["om_coverage_pct"] = float((grid["om_precip"].notna().sum() / grid_len) * 100)
    else:
        coverage["om_coverage_pct"] = 0.0
    
    # Yandex coverage
    if "yx_is_rain" in grid.columns:
        coverage["yx_coverage_pct"] = float((grid["yx_is_rain"].notna().sum() / grid_len) * 100)
    else:
        coverage["yx_coverage_pct"] = 0.0
    
    # Meteostat coverage
    if "ms_precip" in grid.columns:
        coverage["ms_coverage_pct"] = float((grid["ms_precip"].notna().sum() / grid_len) * 100)
    else:
        coverage["ms_coverage_pct"] = 0.0
    
    stats["coverage"] = coverage
'''

print("Add this section after line 168 (after grid_end assignment):")
print(NEW_STATS_SECTION)
