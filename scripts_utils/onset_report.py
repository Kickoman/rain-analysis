#!/usr/bin/env python3
"""
onset_report.py — render the daily report around the one question that matters.
===============================================================================

The reports this replaces ran to 390 lines across eleven sections, of which
exactly one — the ninth — was about predicting the start of rain. The rest
scored "is it raining now", which nothing in the product needs: the alert
exists to fire *before* the first drop, and a model that merely recognises
ongoing rain is worthless for it while topping every nowcast table.

So this renders four things and stops:

  1. the verdict — which candidate to run, at what threshold, what it catches
     and what it costs;
  2. one scoreboard, on onsets only, with error bars and a second independent
     yardstick;
  3. what actually happened in the last day;
  4. whether the data feeding all of it is healthy.

Everything the old sections computed is still in the run's JSON next to the
report; none of it is lost, it is simply no longer the first thing a reader
has to wade through to reach the answer.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

# Reference predictors. They belong in the table as controls — a yardstick that
# says persistence is skilful is broken — but never as a recommendation.
BASELINES = {"persistence", "always_alert", "yandex_forecast"}

VERDICT_MARK = {
    "works": "✅",
    "insufficient_evidence": "…",
    "ranks_only": "◐",
    "one_label_only": "⚠️",
    "chance": "—",
    "unknown": "?",
}

VERDICT_WORD = {
    "works": "beats chance on both yardsticks and beats random at its own threshold",
    "insufficient_evidence": "not yet measurable — too few rain starts in the record",
    "ranks_only": "ranks above chance but has no threshold that beats random alerting",
    "one_label_only": "beats chance on one yardstick only",
    "chance": "not distinguishable from a coin",
    "unknown": "not enough data",
}

DEPLOYED = "ha_live_actual"


def _f(value, digits=2, dash="—"):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return dash
    return f"{value:.{digits}f}"


def _pct(value, digits=0, dash="—"):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return dash
    return f"{value * 100:.{digits}f}%"


def _ci(pair, digits=2):
    if not pair or pair[0] is None or pair[1] is None:
        return "—"
    return f"{pair[0]:.{digits}f}–{pair[1]:.{digits}f}"


def _ci_pct(pair, digits=0):
    if not pair or pair[0] is None or pair[1] is None:
        return "—"
    return f"{pair[0] * 100:.{digits}f}–{pair[1] * 100:.{digits}f}%"


def _front(results: dict) -> dict:
    return (results.get("scoring") or {}).get("front_target") or {}


def _row_sort_key(item):
    """Proven candidates first, then by AUC; baselines always last."""
    name, entry = item
    proven = entry.get("verdict") == "works"
    return (name in BASELINES, not proven, -(entry.get("roc_auc") or 0))


def render_verdict(front: dict) -> list[str]:
    scores = front.get("scores") or {}
    proven = [n for n in (front.get("proven_models") or []) if n not in BASELINES]
    lines = ["## Verdict", ""]

    if not scores:
        return lines + ["Not enough labelled data in this window to answer.", ""]

    if not front.get("enough_evidence", True):
        lines += [
            f"**Too early to say.** The record holds {front.get('n_onsets')} rain starts; "
            f"below {front.get('min_onsets_for_verdict')} the confidence intervals are wider "
            "than any difference between candidates, so this report names no winner. "
            "The scoreboard below is shown for continuity, not for acting on.",
            "",
        ]
        return lines

    if proven:
        # Best proven candidate by what it delivers, not by its ranking metric.
        best = max(proven, key=lambda n: (scores[n].get("events") or {}).get("lift_vs_random") or 0)
        e = scores[best].get("events") or {}
        auc, ci = scores[best].get("roc_auc"), scores[best].get("roc_auc_ci")
        cross = (scores[best].get("cross_label") or {}).get("roc_auc")
        lift = e.get("lift_vs_random")
        lines += [
            f"**Run `{best}` at {_f(e.get('threshold'), 0)}%.** "
            f"It warns before {e.get('onsets_caught')} of {e.get('onsets_total')} rain starts "
            f"({_pct(e.get('event_recall'))}, 95% CI {_ci_pct(e.get('event_recall_ci'))}), "
            f"costs {_f(e.get('alert_hours_per_week'), 0)} alert-hours a week, and gives "
            f"{_f(e.get('median_lead_hours'), 1)} h of warning.",
            "",
        ]
        if lift:
            lines += [
                f"Spreading the same {_f(e.get('alert_hours_per_week'), 0)} alert-hours at random "
                f"would have caught {_f(e.get('expected_caught_if_random'), 1)} of them, so this is "
                f"**{_f(lift)}× better than noise** — real, and not more than that.",
                "",
            ]
        lines += [
            f"Front AUC {_f(auc)} (95% CI {_ci(ci)}), "
            f"{_f(cross)} against the independent Meteostat label.",
            "",
        ]
    else:
        lines += [
            "**Nothing on the board beats a coin toss.** No candidate's confidence "
            "interval clears chance on both yardsticks, so there is no model worth "
            "wiring to a notification this window.",
            "",
        ]

    dep = scores.get(DEPLOYED)
    if dep and dep.get("roc_auc") is None:
        lines += [
            "The deployed sensor `rain_probability` has no usable history in this "
            "window, so it could not be scored here.",
            "",
        ]
    elif dep:
        e = dep.get("events") or {}
        verdict = dep.get("verdict")
        if verdict == "works":
            lines += [f"The deployed sensor `rain_probability` {VERDICT_WORD[verdict]}.", ""]
        else:
            caught = f"{e.get('onsets_caught')} of {e.get('onsets_total')}"
            expected = _f(e.get("expected_caught_if_random"), 1)
            lines += [
                f"**The deployed sensor `rain_probability` is {VERDICT_WORD.get(verdict, 'unmeasured')}** "
                f"— front AUC {_f(dep.get('roc_auc'))} (95% CI {_ci(dep.get('roc_auc_ci'))}). "
                f"It reaches {caught} starts, but alerting at random for as many hours "
                f"({_f(e.get('alert_hours_per_week'), 0)} h/week) would have reached {expected}.",
                "",
            ]

    unproven = [n for n, s in scores.items()
                if n not in BASELINES and s.get("verdict") != "works"]
    if proven and unproven:
        lines += [
            f"The other {len(unproven)} candidates are indistinguishable from chance on "
            f"{front.get('n_onsets')} onsets; differences between them are smaller than "
            "their error bars and should not be acted on.",
            "",
        ]
    return lines


def render_scoreboard(front: dict) -> list[str]:
    scores = front.get("scores") or {}
    if not scores:
        return []
    lines = [
        "## Onset scoreboard",
        "",
        f"From a known-dry hour: does rain *begin* within {front.get('horizon_hours')} h? "
        f"Hours during rain are excluded, so recognising ongoing rain earns nothing. "
        f"An onset is a rain hour after ≥{front.get('dry_hours_before_onset')} known-dry hours.",
        "",
        f"**Window:** {front.get('window_days')} days · **onsets:** {front.get('n_onsets')} "
        f"(Open-Meteo) / {front.get('n_onsets_cross_label')} (Meteostat) · "
        f"**alert budget:** {_f(front.get('alert_budget_hours_per_week'), 0)} h/week",
        "",
        "| Candidate | Catches | If random | Lift | Alert h/wk | Lead | Front AUC (95% CI) | Meteostat AUC | |",
        "|-----------|:-------:|:---------:|:----:|:----------:|:----:|:------------------:|:-------------:|:-:|",
    ]
    for name, s in sorted(scores.items(), key=_row_sort_key):
        e = s.get("events") or {}
        cross = (s.get("cross_label") or {}).get("roc_auc")
        caught = (f"{e.get('onsets_caught')}/{e.get('onsets_total')}"
                  if e.get("onsets_total") is not None else "—")
        label = f"`{name}`" + (" _(control)_" if name in BASELINES else "")
        lines.append(
            f"| {label} | {caught} | {_f(e.get('expected_caught_if_random'), 1)} "
            f"| {_f(e.get('lift_vs_random'))} | {_f(e.get('alert_hours_per_week'), 0)} "
            f"| {_f(e.get('median_lead_hours'), 1)} "
            f"| {_f(s.get('roc_auc'))} ({_ci(s.get('roc_auc_ci'))}) "
            f"| {_f(cross)} | {VERDICT_MARK.get(s.get('verdict'), '?')} |"
        )
    lines += [
        "",
        "_**Catches** — rain starts with an alert in the hours before them. **If random** — "
        "how many the same number of alert-hours would catch scattered at random; **lift** is "
        "the ratio, and anything at or below 1.0 is noise however good its other columns look. "
        "**Lead** — median hours of warning. ✅ = deployable: clears chance on both yardsticks "
        "*and* beats random at its own threshold; ◐ = ranks above chance but has no such "
        "threshold; — = indistinguishable from a coin._",
        "",
    ]
    return lines


def render_last_day(day: str, grid_rows: list[dict] | None, front: dict) -> list[str]:
    """What the recommended model did in the 24 h the report is named after."""
    lines = ["## Last 24 hours", ""]
    if not grid_rows:
        lines += ["_No hourly grid supplied for this run._", ""]
        return lines

    scores = front.get("scores") or {}
    proven = [n for n in (front.get("proven_models") or []) if n not in BASELINES]
    if proven:
        best = max(proven, key=lambda n: (scores[n].get("events") or {}).get("lift_vs_random") or 0)
        caveat = ""
    else:
        # Nothing is proven yet, but "did anything warn last night" is still the
        # question a reader opens the report with. Narrate the leading candidate
        # and say plainly that it is not established.
        ranked = [(n, s.get("roc_auc") or 0) for n, s in scores.items() if n not in BASELINES]
        best = max(ranked, key=lambda r: r[1])[0] if ranked else None
        caveat = " _(leading candidate, not yet proven)_"
    threshold = ((scores.get(best) or {}).get("events") or {}).get("threshold") if best else None

    onsets = [r for r in grid_rows if r.get("is_onset")]
    if not onsets:
        lines.append("No rain started in this window.")
    for r in onsets:
        when = r["time"].strftime("%H:%M")
        if best and threshold is not None and f"warned_{best}" in r:
            warned = r.get(f"warned_{best}")
            mark = "✅ warned" if warned else "❌ no warning"
            lines.append(f"- **{when} UTC** — rain started. `{best}`{caveat}: {mark}.")
        else:
            lines.append(f"- **{when} UTC** — rain started.")
    lines.append("")

    if best and threshold is not None and any(f"alert_{best}" in r for r in grid_rows):
        alert_hours = sum(1 for r in grid_rows if r.get(f"alert_{best}"))
        lines.append(
            f"`{best}` held the alert for {alert_hours} of {len(grid_rows)} hours "
            f"at its {_f(threshold, 0)}% threshold."
        )
        lines.append("")
    return lines


def render_data_health(results: dict) -> list[str]:
    stats = (results.get("metadata") or {}).get("data_stats") or {}
    coverage = stats.get("coverage") or {}
    gt = stats.get("ground_truth") or {}
    lines = ["## Data health", ""]

    labels = {
        "ha_coverage_pct": "local sensors",
        "om_coverage_pct": "Open-Meteo",
        "ms_coverage_pct": "Meteostat",
        "yx_coverage_pct": "Yandex",
    }
    parts = []
    for key, label in labels.items():
        value = coverage.get(key)
        if value is None:
            continue
        flag = "" if value >= 95 else (" ⚠️" if value > 0 else " — absent")
        parts.append(f"{label} {value:.0f}%{flag}")
    if parts:
        lines += ["Coverage over the window: " + ", ".join(parts) + ".", ""]

    rain_hours = gt.get("total_rain_hours")
    labelled = (gt.get("warning_distribution") or {}).get("labelled_hours")
    if rain_hours is not None and labelled:
        lines += [
            f"Ground truth: {rain_hours} rain hours of {labelled} labelled "
            f"({rain_hours / labelled * 100:.1f}% of the window), "
            f"source `{gt.get('source', 'open-meteo')}`.",
            "",
        ]
    lines += [
        "_A local shower can be invisible to every source here: on 2026-08-24 rain "
        "seen from the window, and plain in the sensors, was logged as 0.0 mm by both "
        "Open-Meteo and the Meteostat gauge. Precision figures are therefore a floor, "
        "not an estimate._",
        "",
    ]
    return lines


def generate_report(day: str, results: dict, grid_rows: list[dict] | None = None,
                    generated_at: str | None = None) -> str:
    """Render the whole report. `results` is one full-record run_analysis JSON.

    With no scored onsets at all — the first days of the record, or a window
    where ground truth never saw rain — the scoreboard is omitted rather than
    rendered empty, and the report says why in one line.
    """
    front = _front(results)
    stamp = generated_at or datetime.now(timezone.utc).isoformat()

    lines = [
        f"# Rain Onset Report — {day}",
        "",
        f"**Generated:** {stamp}",
        "",
        f"**The question:** standing in a dry hour, does anything warn that rain "
        f"will start within {front.get('horizon_hours', 3)} hours? Everything else — "
        f"rain that is already falling, when it stops, how much fell — is out of scope.",
        "",
        "---",
        "",
    ]
    if not (front.get("scores") or {}):
        lines += [
            "## Verdict",
            "",
            "**No rain starts in the record yet.** The window holds "
            f"{(results.get('metadata') or {}).get('data_stats', {}).get('coverage', {}).get('grid_rows', 0)} "
            "hours and no onset has been observed in them, so there is nothing to score. "
            "The scoreboard returns as soon as the record contains rain.",
            "",
            "---",
            "",
        ]
        lines += render_data_health(results)
        return "\n".join(lines) + "\n"

    lines += render_verdict(front)
    lines += ["---", ""]
    lines += render_scoreboard(front)
    lines += ["---", ""]
    lines += render_last_day(day, grid_rows, front)
    lines += ["---", ""]
    lines += render_data_health(results)
    lines += [
        "---",
        "",
        "_Full detail for this run — nowcast scores, temporal metrics, source "
        "agreement, sensor diagnostics — is in `analysis_report.json` beside this "
        "file. It is kept out of the report because none of it answers the question "
        "above._",
    ]
    return "\n".join(lines) + "\n"
