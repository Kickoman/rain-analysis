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

def generate_temporal_section(results_7d, results_14d, results_28d, all_models):
    """Generate markdown section for temporal metrics (lead=3h, lag=1h)."""
    section = "## Temporal Metrics (lead=3h, lag=1h)\n\n"
    section += (
        "Scores with prediction-window tolerance: a model predicting rain up to **3 hours early** "
        "or **1 hour late** is still counted as correct. "
        "Best threshold selected by F-beta=2 with min_precision=0.5.\n\n"
    )

    # Table header
    section += "| Model | F1 | Precision | Recall | Best threshold | Window |\n"
    section += "|-------|:---:|:---------:|:------:|:--------------:|--------|\n"

    windows = [("7d", results_7d), ("14d", results_14d), ("28d", results_28d)]

    for model in all_models:
        for window_name, res in windows:
            t = res.get("scoring", {}).get("temporal_scoring", {}).get(model, {})
            if not t or "error" in t:
                section += f"| {model:<20} | N/A | N/A | N/A | N/A | {window_name} |\n"
                continue
            f1 = t.get("f1")
            prec = t.get("precision")
            rec = t.get("recall")
            thr = t.get("best_threshold")
            f1_str = f"{f1:.3f}" if f1 is not None else "N/A"
            prec_str = f"{prec:.3f}" if prec is not None else "N/A"
            rec_str = f"{rec:.3f}" if rec is not None else "N/A"
            thr_str = f"{thr}%" if thr is not None else "N/A"
            section += f"| {model:<20} | {f1_str} | {prec_str} | {rec_str} | {thr_str} | {window_name} |\n"

    section += "\n"
    return section

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


def check_data_overlap(results_7d, results_14d, results_28d):
    """Check if different windows share identical datasets (Issue #157)."""
    windows_data = {}
    
    for name, res in [('7d', results_7d), ('14d', results_14d), ('28d', results_28d)]:
        ds = res['metadata']['data_stats']
        # Handle both old test format (missing grid_start/end) and new format
        windows_data[name] = {
            'start': ds.get('grid_start', 'N/A'),
            'end': ds.get('grid_end', 'N/A'),
            'shape': tuple(ds['grid_shape'])
        }
    
    warnings = []
    
    # Check if 7d and 14d have identical data
    if windows_data['7d']['shape'] == windows_data['14d']['shape']:
        if windows_data['7d']['start'] == windows_data['14d']['start']:
            warnings.append({
                'windows': ['7d', '14d'],
                'reason': 'identical_dataset',
                'shape': windows_data['7d']['shape'],
                'start': windows_data['7d']['start'],
                'end': windows_data['7d']['end']
            })
    
    # Check if 14d and 28d have identical data
    if windows_data['14d']['shape'] == windows_data['28d']['shape']:
        if windows_data['14d']['start'] == windows_data['28d']['start']:
            warnings.append({
                'windows': ['14d', '28d'],
                'reason': 'identical_dataset',
                'shape': windows_data['14d']['shape'],
                'start': windows_data['14d']['start'],
                'end': windows_data['14d']['end']
            })
    
    return windows_data, warnings

# Below this share of the analysis window carrying ground truth, model rankings
# rest on too few labelled hours to be trusted. Meaningful only since coverage
# started being measured over the analysis window on an hourly grid — against
# the old 10-minute grid it could never exceed 16.7%, so it always fired.
LOW_COVERAGE_THRESHOLD = 20.0


def _metric_by_window_rows(all_models, windows, metric: str) -> str:
    """One table row per model, `metric` across the three windows.

    A model with nothing to score renders as N/A. Passing it through as 0.000
    put ha_live_actual at the bottom of every ranking, when in fact
    `sensor.rain_probability` simply has no data outside the recorder window.
    """
    rows = ""
    for model in all_models:
        cells = []
        for window_name in ['7d', '14d', '28d']:
            score = windows[window_name].get('scoring', {}).get('scores', {}).get(model, {})
            value = score.get(metric)
            cells.append("N/A" if value is None or score.get('n_samples') == 0
                         else f"{value:.3f}")
        rows += f"| {model:<20} | {' | '.join(cells)} |\n"
    return rows


def generate_data_context(results_7d) -> str:
    """Ground truth source, per-source coverage, and class balance (7d window).

    One shared renderer: this block used to be pasted verbatim at four points in
    the report, so every reader saw the same numbers four times over.
    """
    meta = results_7d.get('metadata', {})
    data_stats = meta.get('data_stats', {})
    gt_stats = data_stats.get('ground_truth', {})

    out = "## Data Context\n\n"
    out += f"**Ground truth source:** {gt_stats.get('ground_truth_source', 'unknown')}\n\n"

    coverage = data_stats.get('coverage', {})
    if coverage:
        om_cov = coverage.get('om_coverage_pct', 0)
        out += "**Data coverage (7-day window):**\n\n"
        out += f"- Home Assistant sensors: {coverage.get('ha_coverage_pct', 0):.1f}%\n"
        out += f"- Open-Meteo precipitation: {om_cov:.1f}%\n"
        if coverage.get('yx_coverage_pct', 0) > 0:
            out += f"- Yandex Weather: {coverage['yx_coverage_pct']:.1f}%\n"
        if coverage.get('ms_coverage_pct', 0) > 0:
            out += f"- Meteostat: {coverage['ms_coverage_pct']:.1f}%\n"

        if om_cov < LOW_COVERAGE_THRESHOLD:
            out += (f"\n⚠️ **WARNING:** Ground truth coverage below {LOW_COVERAGE_THRESHOLD:.0f}% "
                    f"({om_cov:.1f}%). Model rankings may be unreliable. "
                    "Results should be interpreted with caution.\n")
        out += "\n"

    # What each source actually delivered — a source stuck in the past is
    # invisible in aggregate metrics but obvious here.
    ranges = data_stats.get('source_ranges', {})
    if ranges:
        out += "**Source data ranges:**\n\n"
        for name, info in ranges.items():
            label = name.replace('_', ' ').title()
            if info.get('rows'):
                out += f"- {label}: {info['rows']} rows, {info['first']} → {info['last']}\n"
            else:
                out += f"- {label}: no data\n"
        out += "\n"

    distribution = gt_stats.get('distribution', {})
    if distribution:
        rain_h = distribution.get('rain_hours', 0)
        dry_h = distribution.get('dry_hours', 0)
        unknown_h = distribution.get('unknown_hours', 0)
        labelled = distribution.get('labelled_hours', rain_h + dry_h)

        out += "**Ground truth distribution:**\n\n"
        if labelled > 0:
            # Percentages are of *labelled* hours: sharing them out over the whole
            # grid understated the class balance badly (17/192 = 8.9% showed as 1.5%).
            base_rate = distribution.get('rain_base_rate_pct')
            if base_rate is None:
                base_rate = rain_h / labelled * 100
            out += f"- Rain hours: {rain_h} of {labelled} labelled ({base_rate:.1f}% base rate)\n"
            out += f"- Dry hours: {dry_h}\n"
        else:
            out += f"- Rain hours: {rain_h}\n"
            out += f"- Dry hours: {dry_h}\n"
        if unknown_h > 0:
            out += f"- Unlabelled hours: {unknown_h}\n"
        out += "\n"

    return out


# The replica should reproduce the deployed sensor almost exactly; past this the
# "model comparison" is no longer comparing what actually runs in production.
REPLICA_MAX_MAE = 2.0


def generate_sensor_diagnostics(results_7d) -> str:
    """Local sensor drift, and whether the ha_live replica matches production.

    Models are scored on the raw sensor because that is what production reads.
    This section keeps the sensor's own error visible separately, so a weak model
    score is not mistaken for a calibration fault, or the reverse.
    """
    diagnostics = results_7d.get('cross_check', {}).get('sensor_diagnostics', {})
    if not diagnostics:
        return ""

    out = "## Sensor Diagnostics\n\n"

    comparisons = diagnostics.get('reference_comparisons', {})
    if comparisons:
        out += "Local sensors against reference sources (7d window):\n\n"
        out += "| Comparison | n | Corr | Bias | MAE |\n"
        out += "|------------|:-:|:----:|:----:|:---:|\n"
        for name, stats in comparisons.items():
            label = name.replace('_', ' ')
            out += (f"| {label} | {stats['n']} | {stats['corr']:+.3f} | "
                    f"{stats['bias']:+.2f} | {stats['mae']:.2f} |\n")
        out += "\n"

    replica = diagnostics.get('replica_vs_actual')
    if replica:
        out += "**ha_live replica vs deployed sensor:** "
        out += (f"corr {replica['corr']:.3f}, bias {replica['bias']:+.2f}, "
                f"MAE {replica['mae']:.2f} over {replica['n']} points\n\n")
        if replica['mae'] > REPLICA_MAX_MAE:
            out += (f"⚠️ **WARNING:** replica diverges from production "
                    f"(MAE {replica['mae']:.2f} > {REPLICA_MAX_MAE}). "
                    "Model rankings do not describe the deployed model.\n\n")
    else:
        out += ("_No overlap with `sensor.rain_probability`: it has no long-term "
                "statistics, so it only exists within the recorder retention window._\n\n")

    return out


# Landis & Koch bands for Cohen's kappa. Below "substantial", disagreement
# between the ground-truth sources is a material share of every model's error.
KAPPA_BANDS = [
    (0.80, "almost perfect"),
    (0.60, "substantial"),
    (0.40, "moderate"),
    (0.20, "fair"),
    (0.00, "slight"),
]


def kappa_label(kappa: float) -> str:
    if kappa != kappa:  # NaN
        return "undefined"
    for floor, label in KAPPA_BANDS:
        if kappa >= floor:
            return label
    return "poor"


def generate_ground_truth_agreement(results_7d) -> str:
    """How much the candidate ground-truth sources agree, and whether the model
    ranking survives swapping one for another.

    Raw agreement flatters rare events — two sources that call almost every hour
    dry agree ~85% while telling you nothing — so kappa is reported next to it.
    A ranking that holds under both labels is a property of the models; one that
    reorders is a property of the yardstick.
    """
    cross = results_7d.get('cross_check', {})
    agreement = cross.get('ground_truth_agreement', {})
    pairs = agreement.get('pairs', {})

    out = ""
    if pairs:
        out += "**Ground truth source agreement (chance-corrected):**\n\n"
        out += "| Pair | n | Raw agreement | Cohen's κ | Interpretation |\n"
        out += "|------|:-:|:-------------:|:---------:|----------------|\n"
        for name, stats in pairs.items():
            label = name.replace('_vs_', ' vs ').upper()
            out += (f"| {label} | {stats['n']} | {stats['observed_agreement'] * 100:.1f}% | "
                    f"{stats['kappa']:.3f} | {kappa_label(stats['kappa'])} |\n")
        out += "\n"

        worst = min(s['kappa'] for s in pairs.values() if s['kappa'] == s['kappa'])
        if worst < 0.60:
            out += (f"⚠️ Ground truth sources agree only moderately (κ={worst:.2f}). "
                    "Part of every model's error is the yardstick's, not the model's.\n\n")

    alternative = results_7d.get('scoring', {}).get('scores_vs_meteostat', {})
    primary = results_7d.get('scoring', {}).get('scores', {})
    if alternative and primary:
        out += "**Model F1 under each ground truth:**\n\n"
        out += "| Model | Open-Meteo | Meteostat |\n"
        out += "|-------|:----------:|:---------:|\n"

        def f1_of(source, model):
            value = source.get(model, {}).get('f1')
            return value

        ranked = sorted(primary, key=lambda m: -(f1_of(primary, m) or 0))
        for model in ranked:
            om, ms = f1_of(primary, model), f1_of(alternative, model)
            if om is None and ms is None:
                continue
            out += (f"| {model} | {'N/A' if om is None else f'{om:.3f}'} "
                    f"| {'N/A' if ms is None else f'{ms:.3f}'} |\n")
        out += "\n"

        ranked_alt = sorted(alternative, key=lambda m: -(f1_of(alternative, m) or 0))
        common = [m for m in ranked if m in alternative]
        common_alt = [m for m in ranked_alt if m in primary]
        if common and common == common_alt:
            out += "✅ Ranking is identical under both ground truths — it reflects the models, not the label.\n\n"
        elif common:
            out += (f"⚠️ Ranking changes with the ground truth "
                    f"(Open-Meteo best: **{common[0]}**, Meteostat best: **{common_alt[0]}**). "
                    "Treat the ordering as unresolved.\n\n")

    return out


def _fmt(value, digits=3):
    return "N/A" if value is None else f"{value:.{digits}f}"


def generate_model_quality(results_7d) -> str:
    """Ranking quality, the baseline floor, and the fitted model.

    F1 at a fixed 50% threshold was the only headline number, and it hid models
    that cannot rank at all — `ha_live` posted F1 0.313 while sitting at ROC AUC
    0.579, and `trend_dominant` 0.234 at AUC 0.505, which is a coin flip. ROC
    AUC is threshold-free, so no cutoff can rescue a model that does not
    separate the classes.
    """
    scoring = results_7d.get('scoring', {})
    out = ""

    warning = scoring.get('warning_target') or {}
    if warning.get('scores'):
        horizon = warning.get('horizon_hours')
        out += f"## Warning Target ({horizon}h)\n\n"
        out += (f"Scored against *rain within the next {horizon} hours* — what an alert "
                "actually needs to predict — rather than \"is it raining now\". Ranked by "
                "ROC AUC, because the 50% decision threshold is not calibrated across models.\n\n")
        out += "| Model | ROC AUC | Avg precision | F1 | Precision | Recall |\n"
        out += "|-------|:-------:|:-------------:|:--:|:---------:|:------:|\n"
        ranked = sorted(warning['scores'].items(),
                        key=lambda kv: -(kv[1].get('roc_auc') or 0))
        for name, s in ranked:
            marker = " ✅" if name == warning.get('best_model') else ""
            out += (f"| {name}{marker} | {_fmt(s.get('roc_auc'))} | {_fmt(s.get('average_precision'))} "
                    f"| {_fmt(s.get('f1'))} | {_fmt(s.get('precision'))} | {_fmt(s.get('recall'))} |\n")
        out += "\n_ROC AUC 0.5 is chance. A model at 0.5 is not predicting, whatever its F1._\n\n"

    baselines = scoring.get('baselines') or {}
    if baselines:
        out += "### Baselines\n\n"
        out += ("What any model has to beat. **persistence** = it rained last hour; "
                "**always_alert** = alert unconditionally, so its precision *is* the base "
                "rate; **yandex_forecast** = a free external forecast.\n\n")
        out += "| Baseline | Target | ROC AUC | F1 | Precision | Recall |\n"
        out += "|----------|--------|:-------:|:--:|:---------:|:------:|\n"
        for name, targets in baselines.items():
            for target, s in targets.items():
                out += (f"| {name} | {target} | {_fmt(s.get('roc_auc'))} | {_fmt(s.get('f1'))} "
                        f"| {_fmt(s.get('precision'))} | {_fmt(s.get('recall'))} |\n")
        out += "\n"

        floor = (baselines.get('persistence', {}).get('nowcast', {}) or {}).get('roc_auc')
        best_model_auc = max((s.get('roc_auc') or 0)
                             for s in (scoring.get('scores') or {}).values()) or None
        if floor and best_model_auc and best_model_auc < floor:
            out += (f"⚠️ No model beats persistence (best AUC {best_model_auc:.3f} vs "
                    f"{floor:.3f}). Predicting \"the same as last hour\" is currently the "
                    "strongest thing available.\n\n")

    learned = scoring.get('learned') or {}
    if learned and 'error' not in learned:
        out += "### Fitted model\n\n"
        out += (f"`{learned.get('model')}`, validated walk-forward — trained only on hours "
                "before the ones it is scored on.\n\n")
        out += "| Target | ROC AUC | Avg precision | Held-out rows | Base rate |\n"
        out += "|--------|:-------:|:-------------:|:-------------:|:---------:|\n"
        for target, s in learned.items():
            if not isinstance(s, dict) or 'roc_auc' not in s:
                continue
            out += (f"| {target} | {_fmt(s.get('roc_auc'))} | {_fmt(s.get('average_precision'))} "
                    f"| {s.get('n_scored')} | {_fmt(s.get('base_rate'))} |\n")
        out += "\n"

        # The hand-tuned models scored on exactly the rows the fitted model saw,
        # so the two columns describe the same hours and the same class balance.
        for target, s in learned.items():
            comparison = s.get('comparison_on_same_rows') if isinstance(s, dict) else None
            if not comparison:
                continue
            out += f"**Same held-out rows, {target}:** "
            out += ", ".join(f"{name} {auc:.3f}" for name, auc in list(comparison.items())[:5])
            out += f" — fitted model {_fmt(s.get('roc_auc'))}\n\n"

    return out


def generate_front_section(results_28d, results_7d) -> str:
    """Rain-front scoring: only the dry→rain transition counts.

    Every other target in the report credits hours *during* rain, which is
    what lets persistence outrank the models while being unable to predict a
    single onset from a dry hour. This section is the alert's-eye view.

    Rendered from the 28-day window: onsets are roughly an order of magnitude
    rarer than rain hours, so a 7-day window rarely holds enough of them to
    rank anything — its onset count is stated instead.
    """
    ft = (results_28d.get('scoring', {}) or {}).get('front_target', {})
    scores = ft.get('scores') or {}
    if not scores:
        return ""

    horizon = ft.get('horizon_hours', 3)
    out = "## Rain-Front Prediction (28-day window)\n\n"
    out += (
        f"Scored only on the dry→rain transition: from a known-dry hour, does rain "
        f"*begin* within the next {horizon} hours? Hours during rain are excluded, "
        f"so recognising ongoing rain earns nothing here. An onset is a rain hour "
        f"after ≥{ft.get('dry_hours_before_onset', 3)} known-dry hours.\n\n"
    )
    out += (f"**Onsets in window:** {ft.get('n_onsets')} · "
            f"**base rate from a dry hour:** {_fmt(ft.get('base_rate'))}\n\n")

    out += ("| Candidate | ROC AUC | Dry hours seen | Onsets caught | Precision | Episodes/day | @thr |\n"
            "|-----------|:-------:|:--------------:|:-------------:|:---------:|:------------:|:----:|\n")
    ranked = sorted(scores.items(),
                    key=lambda kv: -(kv[1].get('roc_auc') if kv[1].get('roc_auc') is not None else -1))
    n_onsets = ft.get('n_onsets')
    # Candidates are scored on the dry hours where they had data. When one saw
    # far fewer than the window offers (sensor outage, retention boundary), its
    # AUC is measured on a different — usually easier — subset, and "onsets
    # caught / total" silently blames it for onsets it never saw. The 2026-08-21
    # report ranked models on ~190 of 581 dry hours this way.
    max_n = max((s.get('n_samples') or 0) for s in scores.values()) or 1
    starved = False
    for name, s in ranked:
        ev = s.get('events')
        n_seen = s.get('n_samples')
        if ev:
            caught = f"{ev.get('onsets_caught')}/{n_onsets}"
            prec = _fmt(ev.get('precision'))
            epd = _fmt(ev.get('episodes_per_day'), 2)
            thr = f"{ev.get('threshold'):.0f}%"
        else:
            caught = prec = epd = thr = "N/A"
        seen = str(n_seen) if n_seen is not None else "N/A"
        if n_seen is not None and n_seen < 0.8 * max_n:
            seen += " ⚠️"
            starved = True
        out += (f"| {name:<20} | {_fmt(s.get('roc_auc'))} | {seen} | {caught} "
                f"| {prec} | {epd} | {thr} |\n")
    if starved:
        out += ("\n⚠️ _Candidates marked ⚠️ had data for well under the window\'s dry hours; "
                "their AUC is measured on a different subset and their \"caught\" count "
                "includes onsets they never saw. Compare them with care._\n")

    best = ft.get('best_model')
    if best:
        out += f"\n**Best front predictor:** {best} (by ROC AUC on dry hours)\n"

    learned_front = ((results_28d.get('scoring', {}) or {})
                     .get('learned', {}) or {}).get('front')
    if isinstance(learned_front, dict) and learned_front.get('roc_auc') is not None:
        out += (f"\nFitted model on the same target, walk-forward held-out rows: "
                f"ROC AUC {_fmt(learned_front.get('roc_auc'))} "
                f"({learned_front.get('n_scored')} rows).\n")

    ft7 = (results_7d.get('scoring', {}) or {}).get('front_target', {})
    if ft7.get('n_onsets') is not None:
        out += (f"\n_The 7-day window holds {ft7['n_onsets']} onsets — too few to rank; "
                f"front conclusions here use the 28-day window._\n")

    out += ("\n_A predictor that only recognises ongoing rain scores ~0.5 here "
            "regardless of its warning-target rank; persistence is included as "
            "that control._\n\n")
    return out


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
    
    # Check for data overlap issues (Issue #157)
    windows_data, overlap_warnings = check_data_overlap(results_7d, results_14d, results_28d)
    
    report = f"""# Daily Model Analysis — {date}

**Generated:** {datetime.now(timezone.utc).isoformat()}

**Analysis windows:** 7-day (recent), 14-day (medium-term), 28-day (long-term)

---

"""

    # Add data coverage section if there are warnings (Issue #157)
    if overlap_warnings:
        report += "## ⚠️ Data Coverage Warning\n\n"
        for warn in overlap_warnings:
            windows_str = ' and '.join(warn['windows'])
            report += f"**{windows_str} windows use identical datasets** (shape={warn['shape']}):\n"
            report += f"- Range: {warn['start']} → {warn['end']}\n"
            report += f"- This means metrics for these windows will be identical\n"
            report += f"- Likely cause: insufficient historical data available (<28 days)\n"
            report += f"- Fix: Wait for more data to accumulate, or check `fetch_ha_data.py` for date range issues\n\n"
        
        # Add actual coverage info
        report += "**Actual data coverage:**\n\n"
        for window_name in ['7d', '14d', '28d']:
            wd = windows_data[window_name]
            report += f"- **{window_name}**: {wd['start']} → {wd['end']} (shape={wd['shape']})\n"
        report += "\n---\n\n"
    
    report += f"""## Executive Summary

**Best overall (F-beta=2):** {best_overall_model} @ 7d

**Key findings:**
"""
    
    # Generate key findings
    findings = []
    
    # Check for low ground truth coverage (issue #342)
    meta_7d = results_7d.get('metadata', {})
    coverage = meta_7d.get('data_stats', {}).get('coverage', {})
    om_cov = coverage.get('om_coverage_pct', 0) if coverage else 0

    if om_cov < LOW_COVERAGE_THRESHOLD:
        findings.append(f"⚠️ **WARNING: Low ground truth coverage ({om_cov:.1f}%)** — Model rankings may be unreliable due to insufficient validation data.")
    
    
    # Check if best model is consistent across windows
    best_names = [bm[0] for bm in best_models.values()]
    if len(set(best_names)) == 1:
        findings.append(f"✅ **{best_overall_model}** is best across all windows — strong consistency")
    else:
        findings.append(f"⚠️ Best model varies by window: 7d={best_models['7d'][0]}, 14d={best_models['14d'][0]}, 28d={best_models['28d'][0]}")

    # Front (onset-only) view — the target the alert exists for
    front_28d = results_28d.get('scoring', {}).get('front_target', {})
    if front_28d.get('best_model'):
        findings.append(
            f"🌧️ Best front (onset) predictor: **{front_28d['best_model']}** @ 28d "
            f"({front_28d.get('n_onsets')} onsets)")

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
    report += generate_data_context(results_7d)
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
        status = "✅" if model == best_overall_model else "📊"
        # A model with no scored samples is not a model that scored zero. Rendering
        # both as 0.000 hid the fact that ha_live_actual has no data at all beyond
        # the recorder window, since sensor.rain_probability has no statistics.
        # Reports written before n_samples existed are judged on their metrics.
        no_samples = s.get('n_samples') == 0
        no_metrics = all(s.get(k) is None for k in ('f1', 'precision', 'recall'))
        if no_samples or no_metrics:
            report += f"| {model:<20} | N/A | N/A | N/A | ⚪ no data |\n"
            continue
        f1 = safe_get(s, 'f1')
        p = safe_get(s, 'precision')
        r = safe_get(s, 'recall')
        report += f"| {model:<20} | {f1:.3f} | {p:.3f} | {r:.3f} | {status} |\n"
    
    report += f"\n**Best overall (F-beta=2):** {best_overall_model} @ 7d\n\n"
    report += "---\n\n"
    
    # Temporal metrics section
    report += generate_temporal_section(results_7d, results_14d, results_28d, all_models)
    report += "---\n\n"

    # ===== MULTI-WINDOW COMPARISON =====
    
    report += "## Multi-Window Comparison\n\n"
    report += "Performance across different time windows. F-beta=2 emphasizes recall (catching rain events) while maintaining reasonable precision.\n\n"
    
    # Table: Model × Window (F-beta=2, Precision, Recall)
    report += "### F-beta=2 Scores\n\n"
    report += "| Model | 7d | 14d | 28d | Trend |\n"
    report += "|-------|:---:|:---:|:---:|:------|\n"
    
    for model in all_models:
        # None means no threshold cleared the precision floor in that window.
        # That is not the same as scoring zero, and rendering it as 0.000 made
        # models look like they were "degrading" when they were merely filtered.
        fbeta2_vals = []
        for window_name in ['7d', '14d', '28d']:
            res = windows[window_name]
            fbeta_recs = res.get('scoring', {}).get('fbeta_recommendations', {})
            beta2 = fbeta_recs.get(model, {}).get('beta_2.0', {})
            fbeta2_vals.append(beta2.get('fbeta'))

        first, last = fbeta2_vals[0], fbeta2_vals[2]
        if first is None or last is None:
            trend = "— not comparable"
        elif first > 0 and last > first * 1.1:
            trend = "📈 improving"
        elif first > 0 and last < first * 0.9:
            trend = "📉 degrading"
        else:
            trend = "➡️ stable"

        cells = " | ".join("N/A" if v is None else f"{v:.3f}" for v in fbeta2_vals)
        report += f"| {model:<20} | {cells} | {trend} |\n"

    report += ("\n_N/A means no threshold reached the precision floor in that window — "
               "not a score of zero._\n")
    
    report += "\n### Precision by Window\n\n"
    report += "| Model | 7d | 14d | 28d |\n"
    report += "|-------|:---:|:---:|:---:|\n"
    
    report += _metric_by_window_rows(all_models, windows, 'precision')

    report += "\n### Recall by Window\n\n"
    report += "| Model | 7d | 14d | 28d |\n"
    report += "|-------|:---:|:---:|:---:|\n"

    report += _metric_by_window_rows(all_models, windows, 'recall')


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

    report += "\n"
    report += generate_ground_truth_agreement(results_7d)

    report += "\n---\n\n"

    # ===== MODEL QUALITY: warning target, baselines, fitted model =====
    quality = generate_model_quality(results_7d)
    if quality:
        report += quality
        report += "\n---\n\n"

    # ===== RAIN-FRONT PREDICTION: onset-only scoring =====
    front = generate_front_section(results_28d, results_7d)
    if front:
        report += front
        report += "\n---\n\n"

    # ===== SENSOR DIAGNOSTICS =====
    report += generate_sensor_diagnostics(results_7d)
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

    parser.add_argument(
        "--backend-url",
        default=os.environ.get("RAIN_BACKEND_URL"),
        help="Backend base URL to POST the finished report to "
             "(default: RAIN_BACKEND_URL env; skipped when unset)"
    )

    parser.add_argument(
        "--backend-key",
        default=os.environ.get("RAIN_BACKEND_KEY"),
        help="Write-scoped backend API key (default: RAIN_BACKEND_KEY env)"
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

    # Push the finished report to the backend (variant B, #402): the
    # pipeline stays the only calculator, the backend only stores. Uses the
    # same content builder as the history migration so both paths produce
    # identical structure. Skipped silently when no backend is configured
    # (e.g. CI without secrets).
    if args.backend_url and args.backend_key:
        try:
            import requests
            from migrate_reports_to_backend import build_content

            payload = {
                "report_date": timestamp,
                "content": build_content(report_md),
                "meta": {"source_markdown": report_md, "generator": "daily_analysis.py"},
            }
            response = requests.post(
                args.backend_url.rstrip("/") + "/api/v1/reports",
                json=payload,
                headers={"X-API-Key": args.backend_key},
                timeout=60,
            )
            response.raise_for_status()
            print(f"✓ Report pushed to backend: {response.json().get('action')}")
        except Exception as e:
            # A backend hiccup must not fail the pipeline; the report is
            # already on disk and the migration script repairs gaps.
            print(f"⚠ Backend push failed (report saved locally): {e}")
    elif args.backend_url or args.backend_key:
        print("⚠ Backend push skipped: need BOTH --backend-url and --backend-key")

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
