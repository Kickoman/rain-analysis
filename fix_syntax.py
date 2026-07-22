import sys

# Read the file
with open('run_analysis.py', 'r') as f:
    lines = f.readlines()

# Find the problematic area (around line 167-168)
for i in range(len(lines)):
    if '"grid_end": str(grid.index.max()),' in lines[i]:
        # Check if next line starts coverage stats without closing the dict
        if i + 1 < len(lines) and 'Coverage statistics' in lines[i + 1]:
            # Need to close the stats dict and reopen for coverage
            # Replace the coverage block with proper indentation
            # Find where coverage block ends
            end_idx = i + 1
            while end_idx < len(lines) and 'stats["coverage"] = coverage' not in lines[end_idx]:
                end_idx += 1
            
            if end_idx < len(lines):
                # Replace entire block
                new_block = '''    }

    # Coverage statistics for transparency in reports
    grid_len = len(grid)
    coverage = {}
    
    # HA coverage: any non-NaN value across HA columns
    ha_cols = [c for c in grid.columns if c in ha.columns]
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
                # Delete old lines from i+1 to end_idx
                del lines[i+1:end_idx+1]
                # Insert new block
                lines.insert(i+1, new_block)
                break

# Write back
with open('run_analysis.py', 'w') as f:
    f.writelines(lines)

print("✓ Fixed syntax error in run_analysis.py")
