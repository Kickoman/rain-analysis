import sys

# Read the file
with open('scripts/daily_analysis.py', 'r') as f:
    content = f.read()

# Find where to insert (after "Key findings" section, before model performance table)
# Look for the line "report += "\n---\n\n""
insert_marker = '    report += "\\n---\\n\\n"'

if insert_marker not in content:
    print("ERROR: Could not find insertion point", file=sys.stderr)
    sys.exit(1)

# Prepare the new section
new_section = '''
    # ===== DATA TRANSPARENCY SECTION =====
    # Added for issue #162: surface ground-truth source and data coverage
    
    report += "## Data Context\\n\\n"
    
    # Ground truth source (7d window)
    meta_7d = results_7d.get('metadata', {})
    gt_stats = meta_7d.get('data_stats', {}).get('ground_truth', {})
    gt_source = gt_stats.get('ground_truth_source', 'unknown')
    
    report += f"**Ground truth source:** {gt_source}\\n\\n"
    
    # Data coverage (7d window)
    coverage = meta_7d.get('data_stats', {}).get('coverage', {})
    if coverage:
        report += "**Data coverage (7-day window):**\\n\\n"
        
        ha_cov = coverage.get('ha_coverage_pct', 0)
        om_cov = coverage.get('om_coverage_pct', 0)
        yx_cov = coverage.get('yx_coverage_pct', 0)
        ms_cov = coverage.get('ms_coverage_pct', 0)
        
        report += f"- Home Assistant sensors: {ha_cov:.1f}%\\n"
        report += f"- Open-Meteo precipitation: {om_cov:.1f}%\\n"
        
        if yx_cov > 0:
            report += f"- Yandex Weather: {yx_cov:.1f}%\\n"
        if ms_cov > 0:
            report += f"- Meteostat: {ms_cov:.1f}%\\n"
        
        report += "\\n"
    
    # Ground truth distribution (7d window)
    distribution = gt_stats.get('distribution', {})
    if distribution:
        rain_h = distribution.get('rain_hours', 0)
        dry_h = distribution.get('dry_hours', 0)
        unknown_h = distribution.get('unknown_hours', 0)
        total_h = rain_h + dry_h + unknown_h
        
        report += "**Ground truth distribution:**\\n\\n"
        
        if total_h > 0:
            report += f"- Rain hours: {rain_h} ({rain_h/total_h*100:.1f}%)\\n"
            report += f"- Dry hours: {dry_h} ({dry_h/total_h*100:.1f}%)\\n"
            if unknown_h > 0:
                report += f"- Unknown: {unknown_h} ({unknown_h/total_h*100:.1f}%)\\n"
        else:
            report += f"- Rain hours: {rain_h}\\n"
            report += f"- Dry hours: {dry_h}\\n"
            if unknown_h > 0:
                report += f"- Unknown: {unknown_h}\\n"
        
        report += "\\n"

'''

# Insert before the marker
content = content.replace(insert_marker, new_section + insert_marker)

# Write back
with open('scripts/daily_analysis.py', 'w') as f:
    f.write(content)

print("✓ Patched scripts/daily_analysis.py (added Data Context section)")
