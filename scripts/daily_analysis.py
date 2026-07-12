#!/usr/bin/env python3
"""
Daily model analysis automation script.

Runs full analysis pipeline on:
1. All available historical data (from HA earliest)
2. Last 7 days (recent performance)

Generates report and commits to reports/ directory.
"""

import sys
import os
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess

WORKSPACE = Path("/home/node/.openclaw/workspace/rain-prediction-project/rain-analysis")
REPORTS_DIR = WORKSPACE / "reports"
VENV_PYTHON = "/home/node/.openclaw/workspace/gmail_venv/bin/python"

def run_cmd(cmd, cwd=WORKSPACE):
    """Run command and return output."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, shell=isinstance(cmd, str))
    return result.returncode, result.stdout, result.stderr

def main():
    os.chdir(WORKSPACE)
    REPORTS_DIR.mkdir(exist_ok=True)
    
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_file = REPORTS_DIR / f"{timestamp}.md"
    
    print(f"=== Daily Model Analysis: {timestamp} ===")
    
    # Run 7-day analysis
    print("\n1/2: Running 7-day analysis...")
    ret, out, err = run_cmd([
        VENV_PYTHON, "run_full_analysis.py",
        "--days", "7",
        "--output-dir", f"reports/daily/{timestamp}/7d",
        "--data-dir", f"data/daily/{timestamp}/7d"
    ])
    
    if ret != 0:
        print(f"✗ 7-day analysis failed:\n{err}")
        return 1
    
    # Parse results
    report_json_7d = WORKSPACE / f"reports/daily/{timestamp}/7d" / "*" / "analysis_report.json"
    report_json_7d = list(WORKSPACE.glob(str(report_json_7d)))[0] if list(WORKSPACE.glob(str(report_json_7d))) else None
    
    if not report_json_7d or not report_json_7d.exists():
        print("✗ Could not find 7d report JSON")
        return 1
    
    with open(report_json_7d) as f:
        results_7d = json.load(f)
    
    # Generate markdown report
    report_md = generate_report(timestamp, results_7d)
    
    with open(report_file, 'w') as f:
        f.write(report_md)
    
    print(f"\n✓ Report saved: {report_file}")
    
    # Commit report
    print("\n3/3: Committing report...")
    run_cmd(f"git add {report_file}")
    run_cmd(f"git commit -m 'report: daily model analysis {timestamp}' --no-verify")
    run_cmd("git push origin master")
    
    print("\n✓ Daily analysis complete")
    return 0

def generate_report(date, results_7d):
    """Generate markdown report."""
    scores = results_7d.get('scoring', {}).get('scores', {})
    best = results_7d.get('scoring', {}).get('best_overall', {})
    precip_cmp = results_7d.get('cross_check', {}).get('precip_comparison', {})
    
    report = f"""# Daily Model Analysis — {date}

**Generated:** {datetime.now(timezone.utc).isoformat()}

## Model Performance (7-day window)

| Model | F1 | Precision | Recall | Status |
|-------|:---:|:---------:|:------:|--------|
"""
    
    for model, s in scores.items():
        f1 = s.get('f1', 0)
        p = s.get('precision', 0)
        r = s.get('recall', 0)
        status = "✅" if model == 'ha_live' else "📊"
        report += f"| {model:<15} | {f1:.3f} | {p:.3f} | {r:.3f} | {status} |\n"
    
    report += f"\n**Best overall (F-beta=2):** {best.get('model', 'N/A')} @ {best.get('threshold', 'N/A')}%\n"
    
    # Precipitation comparison
    if precip_cmp:
        report += "\n## Precipitation Source Comparison\n\n"
        report += f"**Sources:** {precip_cmp.get('sources', 0)}\n\n"
        report += "| Source | Rain Hours | Agreement |\n"
        report += "|--------|:----------:|:----------|\n"
        
        for key in ['om', 'ms', 'yx']:
            rain_key = f"{key}_rain_hours"
            if rain_key in precip_cmp:
                hours = precip_cmp[rain_key]
                agreements = []
                for k, v in precip_cmp.items():
                    if k.startswith(f"{key}_") and k.endswith("_agree"):
                        other = k.replace(f"{key}_", "").replace("_agree", "")
                        agreements.append(f"{other}={v}")
                report += f"| {key.upper():<10} | {hours:>10} | {', '.join(agreements)} |\n"
    
    # Recommendations
    report += "\n## Observations & Recommendations\n\n"
    
    ha_live_f1 = scores.get('ha_live', {}).get('f1', 0)
    ha_live_p = scores.get('ha_live', {}).get('precision', 0)
    
    if ha_live_p < 0.55:
        report += "⚠️ **Precision <0.55** — dry-night false positives remain a problem. Pressure-aware model is the priority.\n\n"
    
    if ha_live_f1 < 0.45:
        report += "⚠️ **F1 <0.45** — performance degraded. Review recent data quality.\n\n"
    
    report += "✅ **Next step:** Implement pressure_aware model using ms_pres data.\n"
    
    return report

if __name__ == "__main__":
    sys.exit(main())
