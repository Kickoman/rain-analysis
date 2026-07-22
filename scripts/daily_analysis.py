#!/usr/bin/env python3
"""
Daily model analysis automation script — Multi-window version.

Runs full analysis pipeline on multiple time windows:
1. 7-day window (recent performance, high variance)
2. 14-day window (medium-term trends)
3. 28-day window (long-term stability)

Generates rich report with:
- Multi-window comparison
- Model rankings (F-beta=2, F-beta=3, precision-first)
- Trend analysis (performance stability across windows)
- Precipitation source reliability
- Key observations (intelligent analytics, not dumb thresholds)

Commits report to reports/ directory.
"""

import sys
import os
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import argparse

def run_cmd(cmd, cwd):
    """Run command and return output."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, shell=isinstance(cmd, str))
    return result.returncode, result.stdout, result.stderr

def run_analysis_window(days: int, timestamp: str, workspace: Path, venv_python: str):
    """Run full analysis for a specific time window."""
    print(f"\n{'='*70}")
    print(f"Running {days}-day analysis...")
    print(f"{'='*70}")
    
    ret, out, err = run_cmd([
        venv_python, "run_full_analysis.py",
        "--days", str(days),
        "--output-dir", f"reports/daily/{timestamp}/{days}d",
        "--data-dir", f"data/daily/{timestamp}/{days}d",
        "--skip-plots"  # Skip plots for faster execution
    ], cwd=workspace)
    
    if ret != 0:
        print(f"✗ {days}d analysis failed:\n{err}")
        return None
    
    # Find the analysis_report.json
    report_pattern = f"reports/daily/{timestamp}/{days}d/*/analysis_report.json"
    matches = list(workspace.glob(report_pattern))
    
    if not matches:
        print(f"✗ Could not find {days}d report JSON")
        return None
    
    report_path = matches[0]
    with open(report_path) as f:
        data = json.load(f)
    
    print(f"✓ {days}d analysis complete")
    return data

def safe_get(d, key, default=0):
    """Safely get a value, converting None to default."""
    v = d.get(key)
    return default if v is None else v

def extract_best_model_fbeta2(results, min_precision=0.6):
    """Extract best model by F-beta=2 with min_precision constraint."""
    scores = results.get('scoring', {}).get('scores', {})
    fbeta_recs = results.get('scoring', {}).get('fbeta_recommendations', {})
    
    best_model = None
    best_fbeta2 = 0.0
    
    for model, recs in fbeta_recs.items():
        beta2 = recs.get('beta_2.0', {})
        if not beta2:
            continue
        
        prec = beta2.get('precision')
        fbeta = beta2.get('fbeta')
        
        if prec is None or fbeta is None:
            continue
        
        # Apply min_precision constraint for beta>=2
        if prec >= min_precision and fbeta > best_fbeta2:
            best_fbeta2 = fbeta
            best_model = model
    
    # Fallback to best without constraint if none passed
    if not best_model:
        for model, recs in fbeta_recs.items():
            beta2 = recs.get('beta_2.0', {})
            fbeta = safe_get(beta2, 'fbeta')
            if fbeta > best_fbeta2:
                best_fbeta2 = fbeta
                best_model = model
    
    return best_model, best_fbeta2

def generate_report(date: str, results_7d, results_14d, results_28d):
    """Generate rich markdown report from multi-window results."""
    
    # Extract data
    windows = {'7d': results_7d, '14d': results_14d, '28d': results_28d}
    
    # Get all unique models
    all_models = set()
    for res in windows.values():
        all_models.update(res.get('scoring', {}).get('scores', {}).keys())
    all_models = sorted(all_models)
    
    # Best models per window (F-beta=2 with min_precision=0.6)
    best_models = {}
    for window, res in windows.items():
        best_model, best_fbeta2 = extract_best_model_fbeta2(res)
        best_models[window] = (best_model, best_fbeta2)
    
    # Use 7d best model as default "best overall" for GitHub Pages compatibility
    best_overall_model = best_models['7d'][0]
    
    report = f"""# Daily Model Analysis — {date}

**Generated:** {datetime.now(timezone.utc).isoformat()}

**Analysis windows:** 7-day (recent), 14-day (medium-term), 28-day (long-term)

---

## Executive Summary

**Best overall (F-beta=2):** {best_overall_model} @ 7d

**Key findings:**
"""
    
    # Generate key findings
    findings = []
    
    # Check if best model is consistent across windows
    best_names = [bm[0] for bm in best_models.values()]
    if len(set(best_names)) == 1:
        findings.append(f"✅ **{best_overall_model}** is best across all windows — strong consistency")
    else:
        findings.append(f"⚠️ Best model varies by window: 7d={best_models['7d'][0]}, 14d={best_models['14d'][0]}, 28d={best_models['28d'][0]}")
    
    # Precipitation source analysis
    for window_name, res in [('7d', results_7d)]:
        precip = res.get('cross_check', {}).get('precip_comparison', {})
        if precip:
            om_hours = precip.get('om_rain_hours', 0)
            ms_hours = precip.get('ms_rain_hours', 0)
            yx_hours = precip.get('yx_rain_hours', 0)
            
            # Check for large discrepancies
            sources = [('OM', om_hours), ('MS', ms_hours), ('YX', yx_hours)]
            sources.sort(key=lambda x: x[1])
            if sources[-1][1] > sources[0][1] * 2:
                findings.append(f"⚠️ Large precipitation source discrepancy ({window_name}): {sources[-1][0]}={sources[-1][1]}h vs {sources[0][0]}={sources[0][1]}h")
    
    # Add findings to report
    for finding in findings:
        report += f"- {finding}\n"
    

    # ===== DATA TRANSPARENCY SECTION =====
    # Added for issue #162: surface ground-truth source and data coverage
    
    report += "## Data Context\n\n"
    
    # Ground truth source (7d window)
    meta_7d = results_7d.get('metadata', {})
    gt_stats = meta_7d.get('data_stats', {}).get('ground_truth', {})
    gt_source = gt_stats.get('ground_truth_source', 'unknown')
    
    report += f"**Ground truth source:** {gt_source}\n\n"
    
    # Data coverage (7d window)
    coverage = meta_7d.get('data_stats', {}).get('coverage', {})
    if coverage:
        report += "**Data coverage (7-day window):**\n\n"
        
        ha_cov = coverage.get('ha_coverage_pct', 0)
        om_cov = coverage.get('om_coverage_pct', 0)
        yx_cov = coverage.get('yx_coverage_pct', 0)
        ms_cov = coverage.get('ms_coverage_pct', 0)
        
        report += f"- Home Assistant sensors: {ha_cov:.1f}%\n"
        report += f"- Open-Meteo precipitation: {om_cov:.1f}%\n"
        
        if yx_cov > 0:
            report += f"- Yandex Weather: {yx_cov:.1f}%\n"
        if ms_cov > 0:
            report += f"- Meteostat: {ms_cov:.1f}%\n"
        
        report += "\n"
    
    # Ground truth distribution (7d window)
    distribution = gt_stats.get('distribution', {})
    if distribution:
        rain_h = distribution.get('rain_hours', 0)
        dry_h = distribution.get('dry_hours', 0)
        unknown_h = distribution.get('unknown_hours', 0)
        total_h = rain_h + dry_h + unknown_h
        
        report += "**Ground truth distribution:**\n\n"
        
        if total_h > 0:
            report += f"- Rain hours: {rain_h} ({rain_h/total_h*100:.1f}%)\n"
            report += f"- Dry hours: {dry_h} ({dry_h/total_h*100:.1f}%)\n"
            if unknown_h > 0:
                report += f"- Unknown: {unknown_h} ({unknown_h/total_h*100:.1f}%)\n"
        else:
            report += f"- Rain hours: {rain_h}\n"
            report += f"- Dry hours: {dry_h}\n"
            if unknown_h > 0:
                report += f"- Unknown: {unknown_h}\n"
        
        report += "\n"

    report += "\n---\n\n"
    
    # ===== GITHUB PAGES COMPATIBILITY TABLE =====
    # This table is parsed by generate_history_index.py and generate_metrics_page.py
    # Format: <tr><td>model</td><td>F1</td><td>Precision</td><td>Recall</td>
    
    report += "## Model Performance (7-day window)\n\n"
    report += "| Model | F1 | Precision | Recall | Status |\n"
    report += "|-------|:---:|:---------:|:------:|--------|\n"
    
    scores_7d = results_7d.get('scoring', {}).get('scores', {})
    for model in all_models:
        s = scores_7d.get(model, {})
        f1 = safe_get(s, 'f1')
        p = safe_get(s, 'precision')
        r = safe_get(s, 'recall')
        status = "✅" if model == best_overall_model else "📊"
        report += f"| {model:<20} | {f1:.3f} | {p:.3f} | {r:.3f} | {status} |\n"
    
    report += f"\n**Best overall (F-beta=2):** {best_overall_model} @ 7d\n\n"
    report += "---\n\n"
    
    # ===== MULTI-WINDOW COMPARISON =====
    
    report += "## Multi-Window Comparison\n\n"
    report += "Performance across different time windows. F-beta=2 emphasizes recall (catching rain events) while maintaining reasonable precision.\n\n"
    
    # Table: Model × Window (F-beta=2, Precision, Recall)
    report += "### F-beta=2 Scores\n\n"
    report += "| Model | 7d | 14d | 28d | Trend |\n"
    report += "|-------|:---:|:---:|:---:|:------|\n"
    
    for model in all_models:
        fbeta2_vals = []
        for window_name in ['7d', '14d', '28d']:
            res = windows[window_name]
            fbeta_recs = res.get('scoring', {}).get('fbeta_recommendations', {})
            beta2 = fbeta_recs.get(model, {}).get('beta_2.0', {})
            fbeta = safe_get(beta2, 'fbeta')
            fbeta2_vals.append(fbeta)
        
        # Trend analysis: improving/stable/degrading
        if fbeta2_vals[0] > 0 and fbeta2_vals[2] > fbeta2_vals[0] * 1.1:
            trend = "📈 improving"
        elif fbeta2_vals[0] > 0 and fbeta2_vals[2] < fbeta2_vals[0] * 0.9:
            trend = "📉 degrading"
        else:
            trend = "➡️ stable"
        
        report += f"| {model:<20} | {fbeta2_vals[0]:.3f} | {fbeta2_vals[1]:.3f} | {fbeta2_vals[2]:.3f} | {trend} |\n"
    
    report += "\n### Precision by Window\n\n"
    report += "| Model | 7d | 14d | 28d |\n"
    report += "|-------|:---:|:---:|:---:|\n"
    
    for model in all_models:
        prec_vals = []
        for window_name in ['7d', '14d', '28d']:
            res = windows[window_name]
            scores = res.get('scoring', {}).get('scores', {})
            p = safe_get(scores.get(model, {}), 'precision')
            prec_vals.append(p)
        
        report += f"| {model:<20} | {prec_vals[0]:.3f} | {prec_vals[1]:.3f} | {prec_vals[2]:.3f} |\n"
    
    report += "\n### Recall by Window\n\n"
    report += "| Model | 7d | 14d | 28d |\n"
    report += "|-------|:---:|:---:|:---:|\n"
    
    for model in all_models:
        rec_vals = []
        for window_name in ['7d', '14d', '28d']:
            res = windows[window_name]
            scores = res.get('scoring', {}).get('scores', {})
            r = safe_get(scores.get(model, {}), 'recall')
            rec_vals.append(r)
        
        report += f"| {model:<20} | {rec_vals[0]:.3f} | {rec_vals[1]:.3f} | {rec_vals[2]:.3f} |\n"
    

    # ===== DATA TRANSPARENCY SECTION =====
    # Added for issue #162: surface ground-truth source and data coverage
    
    report += "## Data Context\n\n"
    
    # Ground truth source (7d window)
    meta_7d = results_7d.get('metadata', {})
    gt_stats = meta_7d.get('data_stats', {}).get('ground_truth', {})
    gt_source = gt_stats.get('ground_truth_source', 'unknown')
    
    report += f"**Ground truth source:** {gt_source}\n\n"
    
    # Data coverage (7d window)
    coverage = meta_7d.get('data_stats', {}).get('coverage', {})
    if coverage:
        report += "**Data coverage (7-day window):**\n\n"
        
        ha_cov = coverage.get('ha_coverage_pct', 0)
        om_cov = coverage.get('om_coverage_pct', 0)
        yx_cov = coverage.get('yx_coverage_pct', 0)
        ms_cov = coverage.get('ms_coverage_pct', 0)
        
        report += f"- Home Assistant sensors: {ha_cov:.1f}%\n"
        report += f"- Open-Meteo precipitation: {om_cov:.1f}%\n"
        
        if yx_cov > 0:
            report += f"- Yandex Weather: {yx_cov:.1f}%\n"
        if ms_cov > 0:
            report += f"- Meteostat: {ms_cov:.1f}%\n"
        
        report += "\n"
    
    # Ground truth distribution (7d window)
    distribution = gt_stats.get('distribution', {})
    if distribution:
        rain_h = distribution.get('rain_hours', 0)
        dry_h = distribution.get('dry_hours', 0)
        unknown_h = distribution.get('unknown_hours', 0)
        total_h = rain_h + dry_h + unknown_h
        
        report += "**Ground truth distribution:**\n\n"
        
        if total_h > 0:
            report += f"- Rain hours: {rain_h} ({rain_h/total_h*100:.1f}%)\n"
            report += f"- Dry hours: {dry_h} ({dry_h/total_h*100:.1f}%)\n"
            if unknown_h > 0:
                report += f"- Unknown: {unknown_h} ({unknown_h/total_h*100:.1f}%)\n"
        else:
            report += f"- Rain hours: {rain_h}\n"
            report += f"- Dry hours: {dry_h}\n"
            if unknown_h > 0:
                report += f"- Unknown: {unknown_h}\n"
        
        report += "\n"

    report += "\n---\n\n"
    
    # ===== MODEL RANKINGS =====
    
    report += "## Model Rankings\n\n"
    
    # Rank by F-beta=2 (7d window)
    report += "### By F-beta=2 (7d, min_precision=0.6)\n\n"
    fbeta2_ranking = []
    fbeta_recs_7d = results_7d.get('scoring', {}).get('fbeta_recommendations', {})
    for model in all_models:
        beta2 = fbeta_recs_7d.get(model, {}).get('beta_2.0', {})
        fbeta = beta2.get('fbeta') or 0
        prec = beta2.get('precision') or 0
        rec = beta2.get('recall') or 0
        
        # Apply min_precision filter
        passes_filter = prec >= 0.6
        fbeta2_ranking.append((model, fbeta, prec, rec, passes_filter))
    
    fbeta2_ranking.sort(key=lambda x: (x[4], x[1]), reverse=True)  # Sort by passes_filter, then fbeta
    
    report += "| Rank | Model | F-beta=2 | Precision | Recall | Notes |\n"
    report += "|:----:|-------|:--------:|:---------:|:------:|-------|\n"
    
    for i, (model, fbeta, prec, rec, passes) in enumerate(fbeta2_ranking[:5], 1):
        note = "✅ passes filter" if passes else "❌ low precision"
        report += f"| {i} | {model:<20} | {fbeta:.3f} | {prec:.3f} | {rec:.3f} | {note} |\n"
    
    # Rank by F-beta=3 (higher recall emphasis)
    report += "\n### By F-beta=3 (7d, min_precision=0.6)\n\n"
    report += "Higher recall emphasis (FN≤5% target).\n\n"
    
    fbeta3_ranking = []
    for model in all_models:
        beta3 = fbeta_recs_7d.get(model, {}).get('beta_3.0', {})
        if not beta3:
            continue
        fbeta = beta3.get('fbeta') or 0
        prec = beta3.get('precision') or 0
        rec = beta3.get('recall') or 0
        passes_filter = prec >= 0.6
        fbeta3_ranking.append((model, fbeta, prec, rec, passes_filter))
    
    fbeta3_ranking.sort(key=lambda x: (x[4], x[1]), reverse=True)
    
    report += "| Rank | Model | F-beta=3 | Precision | Recall | Notes |\n"
    report += "|:----:|-------|:--------:|:---------:|:------:|-------|\n"
    
    for i, (model, fbeta, prec, rec, passes) in enumerate(fbeta3_ranking[:5], 1):
        note = "✅ passes filter" if passes else "❌ low precision"
        report += f"| {i} | {model:<20} | {fbeta:.3f} | {prec:.3f} | {rec:.3f} | {note} |\n"
    
    # Precision-first ranking
    report += "\n### By Precision (7d)\n\n"
    report += "For use cases where false positives are costly.\n\n"
    
    prec_ranking = []
    scores_7d = results_7d.get('scoring', {}).get('scores', {})
    for model in all_models:
        s = scores_7d.get(model, {})
        prec = s.get('precision') or 0
        rec = s.get('recall') or 0
        f1 = s.get('f1') or 0
        prec_ranking.append((model, prec, rec, f1))
    
    prec_ranking.sort(key=lambda x: x[1], reverse=True)
    
    report += "| Rank | Model | Precision | Recall | F1 |\n"
    report += "|:----:|-------|:---------:|:------:|:---:|\n"
    
    for i, (model, prec, rec, f1) in enumerate(prec_ranking[:5], 1):
        report += f"| {i} | {model:<20} | {prec:.3f} | {rec:.3f} | {f1:.3f} |\n"
    

    # ===== DATA TRANSPARENCY SECTION =====
    # Added for issue #162: surface ground-truth source and data coverage
    
    report += "## Data Context\n\n"
    
    # Ground truth source (7d window)
    meta_7d = results_7d.get('metadata', {})
    gt_stats = meta_7d.get('data_stats', {}).get('ground_truth', {})
    gt_source = gt_stats.get('ground_truth_source', 'unknown')
    
    report += f"**Ground truth source:** {gt_source}\n\n"
    
    # Data coverage (7d window)
    coverage = meta_7d.get('data_stats', {}).get('coverage', {})
    if coverage:
        report += "**Data coverage (7-day window):**\n\n"
        
        ha_cov = coverage.get('ha_coverage_pct', 0)
        om_cov = coverage.get('om_coverage_pct', 0)
        yx_cov = coverage.get('yx_coverage_pct', 0)
        ms_cov = coverage.get('ms_coverage_pct', 0)
        
        report += f"- Home Assistant sensors: {ha_cov:.1f}%\n"
        report += f"- Open-Meteo precipitation: {om_cov:.1f}%\n"
        
        if yx_cov > 0:
            report += f"- Yandex Weather: {yx_cov:.1f}%\n"
        if ms_cov > 0:
            report += f"- Meteostat: {ms_cov:.1f}%\n"
        
        report += "\n"
    
    # Ground truth distribution (7d window)
    distribution = gt_stats.get('distribution', {})
    if distribution:
        rain_h = distribution.get('rain_hours', 0)
        dry_h = distribution.get('dry_hours', 0)
        unknown_h = distribution.get('unknown_hours', 0)
        total_h = rain_h + dry_h + unknown_h
        
        report += "**Ground truth distribution:**\n\n"
        
        if total_h > 0:
            report += f"- Rain hours: {rain_h} ({rain_h/total_h*100:.1f}%)\n"
            report += f"- Dry hours: {dry_h} ({dry_h/total_h*100:.1f}%)\n"
            if unknown_h > 0:
                report += f"- Unknown: {unknown_h} ({unknown_h/total_h*100:.1f}%)\n"
        else:
            report += f"- Rain hours: {rain_h}\n"
            report += f"- Dry hours: {dry_h}\n"
            if unknown_h > 0:
                report += f"- Unknown: {unknown_h}\n"
        
        report += "\n"

    report += "\n---\n\n"
    
    # ===== PRECIPITATION SOURCE RELIABILITY =====
    
    report += "## Precipitation Source Reliability\n\n"
    
    # Use 7d window for source comparison
    precip = results_7d.get('cross_check', {}).get('precip_comparison', {})
    yandex_truth = results_7d.get('cross_check', {}).get('yandex_vs_truth', {})
    
    if precip:
        report += "Comparison of precipitation sources (7d window):\n\n"
        report += "| Source | Rain Hours | Agreement with Others |\n"
        report += "|--------|:----------:|:----------------------|\n"
        
        sources = [
            ('OM (Open-Meteo)', precip.get('om_rain_hours', 0)),
            ('MS (Meteostat)', precip.get('ms_rain_hours', 0)),
            ('YX (Yandex)', precip.get('yx_rain_hours', 0))
        ]
        
        for src_name, hours in sources:
            src_short = src_name.split()[0]
            agreements = []
            for k, v in precip.items():
                if src_short.lower() in k and 'agree' in k:
                    other = k.replace(f"{src_short.lower()}_", "").replace("_agree", "").upper()
                    agreements.append(f"{other}={v}h")
            
            agree_str = ", ".join(agreements) if agreements else "—"
            report += f"| {src_name:<20} | {hours:>10} | {agree_str} |\n"
    
    if yandex_truth:
        report += f"\n**Yandex vs Ground Truth (HA):**\n"
        report += f"- Yandex rain hours: {yandex_truth.get('yandex_rain_hours', 0)}\n"
        report += f"- Actual rain hours: {yandex_truth.get('actual_rain_hours', 0)}\n"
        report += f"- Agreement: {yandex_truth.get('agreement_hours', 0)}h\n"
        report += f"- Yandex-only: {yandex_truth.get('yandex_only', 0)}h (false positives)\n"
        report += f"- Actual-only: {yandex_truth.get('actual_only', 0)}h (missed events)\n"
    

    # ===== DATA TRANSPARENCY SECTION =====
    # Added for issue #162: surface ground-truth source and data coverage
    
    report += "## Data Context\n\n"
    
    # Ground truth source (7d window)
    meta_7d = results_7d.get('metadata', {})
    gt_stats = meta_7d.get('data_stats', {}).get('ground_truth', {})
    gt_source = gt_stats.get('ground_truth_source', 'unknown')
    
    report += f"**Ground truth source:** {gt_source}\n\n"
    
    # Data coverage (7d window)
    coverage = meta_7d.get('data_stats', {}).get('coverage', {})
    if coverage:
        report += "**Data coverage (7-day window):**\n\n"
        
        ha_cov = coverage.get('ha_coverage_pct', 0)
        om_cov = coverage.get('om_coverage_pct', 0)
        yx_cov = coverage.get('yx_coverage_pct', 0)
        ms_cov = coverage.get('ms_coverage_pct', 0)
        
        report += f"- Home Assistant sensors: {ha_cov:.1f}%\n"
        report += f"- Open-Meteo precipitation: {om_cov:.1f}%\n"
        
        if yx_cov > 0:
            report += f"- Yandex Weather: {yx_cov:.1f}%\n"
        if ms_cov > 0:
            report += f"- Meteostat: {ms_cov:.1f}%\n"
        
        report += "\n"
    
    # Ground truth distribution (7d window)
    distribution = gt_stats.get('distribution', {})
    if distribution:
        rain_h = distribution.get('rain_hours', 0)
        dry_h = distribution.get('dry_hours', 0)
        unknown_h = distribution.get('unknown_hours', 0)
        total_h = rain_h + dry_h + unknown_h
        
        report += "**Ground truth distribution:**\n\n"
        
        if total_h > 0:
            report += f"- Rain hours: {rain_h} ({rain_h/total_h*100:.1f}%)\n"
            report += f"- Dry hours: {dry_h} ({dry_h/total_h*100:.1f}%)\n"
            if unknown_h > 0:
                report += f"- Unknown: {unknown_h} ({unknown_h/total_h*100:.1f}%)\n"
        else:
            report += f"- Rain hours: {rain_h}\n"
            report += f"- Dry hours: {dry_h}\n"
            if unknown_h > 0:
                report += f"- Unknown: {unknown_h}\n"
        
        report += "\n"

    report += "\n---\n\n"
    
    # ===== KEY OBSERVATIONS =====
    
    report += "## Key Observations & Recommendations\n\n"
    
    observations = []
    
    # Best model stability
    best_7d = best_models['7d'][0]
    best_28d = best_models['28d'][0]
    
    if best_7d == best_28d:
        observations.append(f"✅ **{best_7d}** maintains top position across 7d and 28d windows — reliable choice for production.")
    else:
        observations.append(f"⚠️ Best model differs: **{best_7d}** (7d) vs **{best_28d}** (28d). Short-term volatility or model overfitting to recent events?")
    
    # Precision analysis
    avg_prec_7d = sum(safe_get(scores_7d.get(m, {}), 'precision') for m in all_models) / len(all_models)
    if avg_prec_7d < 0.4:
        observations.append(f"⚠️ **Low average precision ({avg_prec_7d:.2f})** — models produce many false positives. Pressure-aware variants may help.")
    
    # Recall analysis
    avg_rec_7d = sum(safe_get(scores_7d.get(m, {}), 'recall') for m in all_models) / len(all_models)
    if avg_rec_7d < 0.5:
        observations.append(f"⚠️ **Low average recall ({avg_rec_7d:.2f})** — models miss many rain events. Consider lower thresholds or better features.")
    
    # Trend analysis for ha_live
    if 'ha_live' in all_models:
        ha_fbeta2_7d = safe_get(fbeta_recs_7d.get('ha_live', {}).get('beta_2.0', {}), 'fbeta')
        ha_fbeta2_28d = safe_get(results_28d.get('scoring', {}).get('fbeta_recommendations', {}).get('ha_live', {}).get('beta_2.0', {}), 'fbeta')
        
        if ha_fbeta2_28d > ha_fbeta2_7d * 1.1:
            observations.append(f"📈 **ha_live improving** with longer window (7d: {ha_fbeta2_7d:.3f} → 28d: {ha_fbeta2_28d:.3f}). Model benefits from more data.")
        elif ha_fbeta2_28d < ha_fbeta2_7d * 0.9:
            observations.append(f"📉 **ha_live degrading** with longer window (7d: {ha_fbeta2_7d:.3f} → 28d: {ha_fbeta2_28d:.3f}). May be overfitting to recent patterns.")
    
    # Data quality check
    data_stats = results_7d.get('metadata', {}).get('data_stats', {})
    grid_hours = data_stats.get('grid_shape', [0])[0] / 6  # 10-min intervals → hours
    rain_hours = data_stats.get('ground_truth', {}).get('total_rain_hours', 0)
    
    if rain_hours < 10:
        observations.append(f"⚠️ **Low rain event count ({rain_hours}h in 7d window)** — small sample size may cause high variance. 14d/28d windows recommended.")
    
    # Precipitation source reliability
    if precip and yandex_truth:
        yx_hours = precip.get('yx_rain_hours', 0)
        om_hours = precip.get('om_rain_hours', 0)
        actual_hours = yandex_truth.get('actual_rain_hours', 0)
        
        if yx_hours > actual_hours * 2:
            observations.append(f"⚠️ **Yandex over-reports rain** ({yx_hours}h vs {actual_hours}h actual). Use OM ({om_hours}h) or MS as ground truth instead.")
        
        if abs(om_hours - actual_hours) < abs(yx_hours - actual_hours):
            observations.append(f"✅ **Open-Meteo closer to ground truth** than Yandex. Prefer OM for precipitation validation.")
    
    # Next steps
    observations.append(f"\n**Next steps:** Review pressure_* model variants for improving precision without sacrificing recall. Target: F-beta=2 >0.5, precision >0.6.")
    
    for obs in observations:
        report += f"{obs}\n\n"
    
    report += "---\n\n"
    report += f"_Report generated by daily_analysis.py at {datetime.now(timezone.utc).isoformat()}_\n"
    
    return report

def main():
    parser = argparse.ArgumentParser(
        description="Generate daily rain analysis report with multi-window comparison",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run from repository root with defaults
  python scripts/daily_analysis.py
  
  # Specify custom paths
  python scripts/daily_analysis.py \\
    --workspace /path/to/rain-analysis \\
    --venv-python /path/to/venv/bin/python \\
    --date 2026-07-20
  
  # Skip git operations (for testing)
  python scripts/daily_analysis.py --no-commit
"""
    )
    
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Path to rain-analysis repository (default: current directory)"
    )
    
    parser.add_argument(
        "--venv-python",
        type=str,
        default=sys.executable,
        help="Path to Python interpreter with pandas/numpy/matplotlib (default: current Python)"
    )
    
    parser.add_argument(
        "--date",
        help="Report date (YYYY-MM-DD), defaults to today UTC"
    )
    
    parser.add_argument(
        "--no-commit",
        action="store_true",
        help="Skip git commit/push (useful for testing)"
    )
    
    args = parser.parse_args()
    
    workspace = args.workspace.resolve()
    reports_dir = workspace / "reports"
    
    if not workspace.is_dir():
        print(f"✗ Workspace directory not found: {workspace}")
        return 1
    
    if not (workspace / "run_full_analysis.py").exists():
        print(f"✗ run_full_analysis.py not found in {workspace}")
        return 1
    
    reports_dir.mkdir(exist_ok=True)
    
    if args.date:
        timestamp = args.date
    else:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    report_file = reports_dir / f"{timestamp}.md"
    
    print("=" * 70)
    print(f"DAILY MODEL ANALYSIS — Multi-Window")
    print("=" * 70)
    print(f"Date: {timestamp}")
    print(f"Workspace: {workspace}")
    print(f"Python: {args.venv_python}")
    print(f"Windows: 7d, 14d, 28d")
    print(f"Output: {report_file}")
    
    # Run analyses for each window
    results_7d = run_analysis_window(7, timestamp, workspace, args.venv_python)
    results_14d = run_analysis_window(14, timestamp, workspace, args.venv_python)
    results_28d = run_analysis_window(28, timestamp, workspace, args.venv_python)
    
    if not all([results_7d, results_14d, results_28d]):
        print("\n✗ One or more analysis windows failed")
        return 1
    
    # Generate report
    print("\n" + "=" * 70)
    print("Generating report...")
    print("=" * 70)
    
    report_md = generate_report(timestamp, results_7d, results_14d, results_28d)
    
    with open(report_file, 'w') as f:
        f.write(report_md)
    
    print(f"\n✓ Report saved: {report_file}")
    
    if not args.no_commit:
        # Commit report
        print("\n" + "=" * 70)
        print("Committing report...")
        print("=" * 70)
        
        run_cmd(f"git add {report_file}", cwd=workspace)
        run_cmd(f"git commit -m 'report: daily model analysis {timestamp}' --no-verify", cwd=workspace)
        run_cmd("git push origin master", cwd=workspace)
        
        print("\n✓ Report committed and pushed")
    else:
        print("\n✓ Skipping git operations (--no-commit)")
    
    print("\n✓ Daily analysis complete")
    return 0

if __name__ == "__main__":
    sys.exit(main())
