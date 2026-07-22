import sys

# Read the file
with open('run_analysis.py', 'r') as f:
    lines = f.readlines()

# Find the line with '"ground_truth_source": gt_source,' (around line 252)
insert_after = -1
for i, line in enumerate(lines):
    if '"ground_truth_source": gt_source,' in line:
        insert_after = i
        break

if insert_after == -1:
    print("ERROR: Could not find ground_truth_source line", file=sys.stderr)
    sys.exit(1)

# Prepare the distribution block
distribution_block = '''        "distribution": {
            "rain_hours": int((grid["rain_truth"] == 1).sum()),
            "dry_hours": int((grid["rain_truth"] == 0).sum()),
            "unknown_hours": int(grid["rain_truth"].isna().sum()),
        },
'''

# Insert after ground_truth_source line
lines.insert(insert_after + 1, distribution_block)

# Write back
with open('run_analysis.py', 'w') as f:
    f.writelines(lines)

print(f"✓ Patched run_analysis.py (inserted distribution stats after line {insert_after + 1})")
