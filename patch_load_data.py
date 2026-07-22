import sys

# Read the file
with open('run_analysis.py', 'r') as f:
    lines = f.readlines()

# Find the line with "grid_end" assignment (around line 168)
insert_after = -1
for i, line in enumerate(lines):
    if '"grid_end": str(grid.index.max()),' in line:
        insert_after = i
        break

if insert_after == -1:
    print("ERROR: Could not find grid_end line", file=sys.stderr)
    sys.exit(1)

# Prepare the coverage stats block
coverage_block = '''
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

# Insert after grid_end line
lines.insert(insert_after + 1, coverage_block)

# Write back
with open('run_analysis.py', 'w') as f:
    f.writelines(lines)

print(f"✓ Patched run_analysis.py (inserted coverage stats after line {insert_after + 1})")
