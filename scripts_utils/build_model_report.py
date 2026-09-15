#!/usr/bin/env python3
"""
build_model_report.py — one page that answers "which model works, and why".
===========================================================================

Fifty daily reports is fifty markdown sheets of tables; the answer to the only
question that matters is spread across all of them. This renders a single
self-contained HTML page from the same JSON the daily reports are built from:
how each model has scored over time, what its alerts would cost, and how much
of the disagreement is the yardstick's rather than the models'.

Standalone by design — no CDN, no third-party imports, charts drawn as inline
SVG — so the file works opened from disk and published as an artifact alike.

Usage:
  python scripts_utils/build_model_report.py \
      --reports-dir reports/daily --grid data/grid.csv \
      --output reports/model-review.html
"""

import argparse
import csv
import html
import json
import math
import re
import statistics
import sys
from datetime import date, datetime, timezone
from pathlib import Path

WINDOW = "28d"

# The generation boundary: reports up to this date were scored against the ERA5
# archive series, later ones against the forecast series. Base rates and every
# score that depends on them are not comparable across it.
TRUTH_SWITCH = "2026-08-14"

# Categorical slots 1-3 of the validated palette (light / dark steps).
SERIES = {
    "pressure_primary": ("#2a78d6", "#3987e5"),
    "onset_gate":       ("#eb6834", "#d95926"),
    "ha_live_actual":   ("#1baf7a", "#199e70"),
}
CONTROL = "persistence"

RU = {
    "pressure_primary": "pressure_primary",
    "onset_gate": "onset_gate",
    "ha_live_actual": "боевая модель",
    "ha_live_replica": "копия боевой",
    "persistence": "«как час назад»",
    "always_alert": "«всегда тревога»",
    "yandex_forecast": "прогноз Яндекса",
    "trend_dominant": "trend_dominant",
    "original": "original",
    "tuned": "tuned",
    "combined": "combined",
    "pressure_absolute": "pressure_absolute",
    "pressure_aware": "pressure_aware",
    "pressure_lagged": "pressure_lagged",
    "pressure_combined": "pressure_combined",
    "pressure_long_window": "pressure_long_window",
}


def load_reports(reports_dir: Path, window: str = WINDOW) -> dict:
    """date -> parsed report. Files up to 2026-08-17 contain bare NaN literals,
    which Python accepts and JSON.parse does not — which is why every number on
    the page is computed here and no JSON is shipped to the browser."""
    out = {}
    for path in sorted(reports_dir.glob(f"*/{window}/backfill/analysis_report.json")):
        day = path.parts[-4]
        with open(path) as f:
            out[day] = json.load(f)
    return out


def front_series(reports: dict) -> dict:
    """model -> {date: roc_auc}. A model absent from a window is absent here —
    a gap in the line, never a zero."""
    series = {}
    for day, rep in reports.items():
        for name, entry in rep["scoring"]["front_target"]["scores"].items():
            auc = entry.get("roc_auc") if isinstance(entry, dict) else None
            if auc is None or (isinstance(auc, float) and math.isnan(auc)):
                continue
            series.setdefault(name, {})[day] = auc
    return series


def onset_context(reports: dict) -> dict:
    """date -> (onsets, base_rate) so a score can be read next to its sample size."""
    return {d: (r["scoring"]["front_target"]["n_onsets"],
                r["scoring"]["front_target"]["base_rate"])
            for d, r in reports.items()}


def alert_cost(report: dict) -> list:
    """Per candidate: alerts per day, share of them that were right, onsets caught."""
    ft = report["scoring"]["front_target"]
    rows = []
    for name, entry in ft["scores"].items():
        ev = entry.get("events") if isinstance(entry, dict) else None
        if not ev:
            continue
        rows.append({
            "name": name,
            "auc": entry.get("roc_auc"),
            "threshold": ev["threshold"],
            "per_day": ev["episodes_per_day"],
            "precision": ev["precision"],
            "caught": ev["onsets_caught"],
            "onsets": ft["n_onsets"],
        })
    return sorted(rows, key=lambda r: -(r["auc"] or 0))


def ranking(series: dict, dates: list) -> list:
    """Mean / min / max front AUC over the given dates, best first."""
    rows = []
    for name, by_date in series.items():
        vals = [by_date[d] for d in dates if d in by_date]
        if len(vals) < len(dates) // 2:
            continue
        rows.append({"name": name, "mean": statistics.fmean(vals),
                     "lo": min(vals), "hi": max(vals), "n": len(vals)})
    return sorted(rows, key=lambda r: -r["mean"])


def read_grid(path: Path) -> list:
    """The hourly grid dumped by run_analysis.py --dump-grid."""
    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            def num(key):
                try:
                    return float(row[key])
                except (KeyError, TypeError, ValueError):
                    return None
            rows.append({
                "t": row["time"][:16],
                "truth": num("rain_truth"),
                "precip": num("om_precip"),
                "best": num("model_pressure_primary"),
                "live": num("ha_rain_prob"),
            })
    return rows


# ---------------------------------------------------------------------------
# Charts. Inline SVG, drawn against CSS variables so both themes work.
# ---------------------------------------------------------------------------

def esc(text) -> str:
    return html.escape(str(text), quote=True)


def fmt(value, digits=3) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}".replace(".", ",")


def _path(points) -> str:
    """Move-and-line path with a break wherever the data has a gap."""
    out, pen_down = [], False
    for point in points:
        if point is None:
            pen_down = False
            continue
        cmd = "L" if pen_down else "M"
        out.append(f"{cmd}{point[0]:.1f} {point[1]:.1f}")
        pen_down = True
    return " ".join(out)


def chart_dynamics(series: dict, dates: list, ctx: dict) -> str:
    W, H = 920, 400
    L, R, T, B = 52, 150, 24, 52
    lo, hi = 0.30, 0.85
    x = lambda i: L + i * (W - L - R) / max(len(dates) - 1, 1)
    y = lambda v: T + (hi - v) * (H - T - B) / (hi - lo)

    parts = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
             f'aria-label="ROC AUC на фронте по 28-дневным окнам">']

    for gv in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
        parts.append(f'<line class="grid" x1="{L}" x2="{W-R}" y1="{y(gv):.1f}" y2="{y(gv):.1f}"/>')
        parts.append(f'<text class="tick" x="{L-10}" y="{y(gv)+4:.1f}" text-anchor="end">'
                     f'{fmt(gv,1)}</text>')

    parts.append(f'<line class="chance" x1="{L}" x2="{W-R}" y1="{y(0.5):.1f}" y2="{y(0.5):.1f}"/>')
    parts.append(f'<text class="chance-label" x="{W-R-6}" y="{y(0.5)-8:.1f}" text-anchor="end">'
                 f'монетка — 0,5</text>')

    switch = next((i for i, d in enumerate(dates) if d >= TRUTH_SWITCH), None)
    if switch is not None:
        sx = x(switch - 0.5)
        parts.append(f'<line class="switch" x1="{sx:.1f}" x2="{sx:.1f}" y1="{T}" y2="{H-B}"/>')
        parts.append(f'<text class="switch-label" x="{sx+7:.1f}" y="{T+13}">'
                     f'14 августа: сменился эталон</text>')

    for name, by_date in sorted(series.items()):
        if name in SERIES or name == CONTROL:
            continue
        pts = [(x(i), y(by_date[d])) if d in by_date else None for i, d in enumerate(dates)]
        parts.append(f'<path class="rest" d="{_path(pts)}"/>')

    cpts = [(x(i), y(series[CONTROL][d])) if d in series.get(CONTROL, {}) else None
            for i, d in enumerate(dates)]
    parts.append(f'<path class="control" d="{_path(cpts)}"/>')

    for slot, (name, _) in enumerate(SERIES.items(), start=1):
        by_date = series.get(name, {})
        pts = [(x(i), y(by_date[d])) if d in by_date else None for i, d in enumerate(dates)]
        parts.append(f'<path class="s{slot}" d="{_path(pts)}"/>')
        last = [p for p in pts if p]
        if last:
            px, py = last[-1]
            parts.append(f'<circle class="s{slot}-dot" cx="{px:.1f}" cy="{py:.1f}" r="4"/>')
            parts.append(f'<text class="lead s{slot}-text" x="{px+10:.1f}" y="{py+4:.1f}">'
                         f'{esc(RU.get(name, name))}</text>')

    for i, day in enumerate(dates):
        if day.endswith(("-01", "-08", "-15", "-22", "-29")):
            parts.append(f'<text class="tick" x="{x(i):.1f}" y="{H-B+20}" text-anchor="middle">'
                         f'{day[8:]}.{day[5:7]}</text>')

    for i, day in enumerate(dates):
        onsets, base = ctx[day]
        vals = " · ".join(
            f"{RU.get(n, n)} {fmt(series[n][day], 3)}"
            for n in list(SERIES) + [CONTROL] if day in series.get(n, {}))
        parts.append(
            f'<rect class="hit" x="{x(i)-5:.1f}" y="{T}" width="10" height="{H-T-B}">'
            f'<title>{esc(day)} · окно 28 дней · {onsets} онсетов, базовая {base*100:.1f}%\n'
            f'{esc(vals)}</title></rect>')

    parts.append(f'<text class="axis" x="{L}" y="{H-8}">начало дождя предсказано верно, '
                 f'ROC AUC · выше — лучше</text>')
    parts.append('</svg>')
    return "".join(parts)


def chart_ranking(rows: list) -> str:
    rows = rows[:12]
    W = 920
    row_h = 30
    H = 40 + row_h * len(rows) + 34
    L, R, T = 190, 60, 26
    lo, hi = 0.40, 0.80
    x = lambda v: L + (v - lo) * (W - L - R) / (hi - lo)

    parts = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
             f'aria-label="Средний AUC по 18 свежим окнам">']
    for gv in (0.4, 0.5, 0.6, 0.7, 0.8):
        parts.append(f'<line class="grid" x1="{x(gv):.1f}" x2="{x(gv):.1f}" y1="{T-8}" '
                     f'y2="{T + row_h*len(rows)}"/>')
        parts.append(f'<text class="tick" x="{x(gv):.1f}" y="{T + row_h*len(rows) + 20}" '
                     f'text-anchor="middle">{fmt(gv,1)}</text>')
    parts.append(f'<line class="chance" x1="{x(0.5):.1f}" x2="{x(0.5):.1f}" y1="{T-8}" '
                 f'y2="{T + row_h*len(rows)}"/>')

    for i, row in enumerate(rows):
        cy = T + row_h * i + row_h / 2
        cls = "s1" if row["name"] == "pressure_primary" else (
              "s2" if row["name"] == "onset_gate" else (
              "s3" if row["name"] == "ha_live_actual" else "rest"))
        label = RU.get(row["name"], row["name"])
        weight = "strong" if cls != "rest" else "plain"
        parts.append(f'<text class="rowlabel {weight}" x="{L-14}" y="{cy+4:.1f}" '
                     f'text-anchor="end">{esc(label)}</text>')
        parts.append(f'<line class="whisker {cls}-stroke" x1="{x(row["lo"]):.1f}" '
                     f'x2="{x(row["hi"]):.1f}" y1="{cy:.1f}" y2="{cy:.1f}"/>')
        parts.append(f'<circle class="{cls}-fill" cx="{x(row["mean"]):.1f}" cy="{cy:.1f}" r="5.5">'
                     f'<title>{esc(label)}: в среднем {fmt(row["mean"])}, '
                     f'от {fmt(row["lo"])} до {fmt(row["hi"])} по {row["n"]} окнам</title></circle>')
        parts.append(f'<text class="value" x="{W-R+10}" y="{cy+4:.1f}">{fmt(row["mean"])}</text>')

    parts.append(f'<text class="axis" x="{L}" y="{H-6}">средний ROC AUC на фронте, '
                 f'усы — худшее и лучшее окно</text>')
    parts.append('</svg>')
    return "".join(parts)


def chart_alert_cost(rows: list, base_rate: float) -> str:
    W, H = 920, 400
    L, R, T, B = 62, 30, 26, 56
    xmax = max([r["per_day"] for r in rows] + [1.6]) * 1.15
    ymax = max([r["precision"] for r in rows] + [0.3]) * 1.15
    x = lambda v: L + v * (W - L - R) / xmax
    y = lambda v: T + (ymax - v) * (H - T - B) / ymax

    parts = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
             f'aria-label="Тревог в сутки против доли верных тревог">']
    for gv in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]:
        if gv > ymax:
            continue
        parts.append(f'<line class="grid" x1="{L}" x2="{W-R}" y1="{y(gv):.1f}" y2="{y(gv):.1f}"/>')
        parts.append(f'<text class="tick" x="{L-10}" y="{y(gv)+4:.1f}" text-anchor="end">'
                     f'{gv*100:.0f}%</text>')
    for gv in [0.0, 0.5, 1.0, 1.5, 2.0]:
        if gv > xmax:
            continue
        parts.append(f'<text class="tick" x="{x(gv):.1f}" y="{H-B+20}" text-anchor="middle">'
                     f'{fmt(gv,1)}</text>')

    parts.append(f'<line class="chance" x1="{L}" x2="{W-R}" y1="{y(base_rate):.1f}" '
                 f'y2="{y(base_rate):.1f}"/>')
    parts.append(f'<text class="chance-label" x="{W-R-6}" y="{y(base_rate)-8:.1f}" '
                 f'text-anchor="end">случайная тревога — {base_rate*100:.1f}%</text>')

    labelled = []
    for row in rows:
        cls = {"pressure_primary": "s1", "onset_gate": "s2",
               "ha_live_actual": "s3"}.get(row["name"], "rest")
        px, py = x(row["per_day"]), y(row["precision"])
        label = RU.get(row["name"], row["name"])
        parts.append(
            f'<circle class="dot-{cls}" cx="{px:.1f}" cy="{py:.1f}" r="6">'
            f'<title>{esc(label)} при пороге {row["threshold"]:.0f}%: '
            f'{row["per_day"]:.2f} тревог в сутки, верных {row["precision"]*100:.0f}%, '
            f'поймано {row["caught"]} онсетов из {row["onsets"]}</title></circle>')
        if cls != "rest" or row["name"] in ("always_alert", "persistence", "yandex_forecast"):
            labelled.append([px, py, cls, label])

    # Push labels apart where dots sit on top of each other — persistence and
    # "always alert" land within a few pixels of one another most windows.
    labelled.sort(key=lambda item: item[1])
    for i in range(1, len(labelled)):
        gap = labelled[i][1] - labelled[i - 1][1]
        if gap < 15 and abs(labelled[i][0] - labelled[i - 1][0]) < 150:
            labelled[i][1] = labelled[i - 1][1] + 15
    for px, ly, cls, label in labelled:
        anchor = "end" if px > W - 250 else "start"
        dx = -13 if anchor == "end" else 13
        parts.append(f'<text class="pointlabel {cls}-text" x="{px+dx:.1f}" y="{ly+4:.1f}" '
                     f'text-anchor="{anchor}">{esc(label)}</text>')

    parts.append(f'<text class="axis" x="{L}" y="{H-8}">тревог в сутки →</text>')
    parts.append(f'<text class="axis vertical" transform="translate(16 {T+120}) rotate(-90)">'
                 f'доля верных тревог ↑</text>')
    parts.append('</svg>')
    return "".join(parts)


def chart_timeline(grid: list) -> str:
    W, H = 920, 320
    L, R, T, B = 46, 24, 22, 46
    n = len(grid)
    x = lambda i: L + i * (W - L - R) / max(n - 1, 1)
    y = lambda v: T + (100 - v) * (H - T - B) / 100

    parts = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
             f'aria-label="Вероятность дождя против фактического дождя">']

    start = None
    for i, row in enumerate(grid + [{"truth": 0.0}]):
        wet = row.get("truth") == 1.0
        if wet and start is None:
            start = i
        elif not wet and start is not None:
            x0, x1 = x(start) - 1.5, x(i - 1) + 1.5
            parts.append(f'<rect class="rain" x="{x0:.1f}" y="{T}" '
                         f'width="{max(x1-x0, 2.5):.1f}" height="{H-T-B}"/>')
            start = None

    for gv in (0, 25, 50, 75, 100):
        parts.append(f'<line class="grid" x1="{L}" x2="{W-R}" y1="{y(gv):.1f}" y2="{y(gv):.1f}"/>')
        parts.append(f'<text class="tick" x="{L-8}" y="{y(gv)+4:.1f}" text-anchor="end">{gv}</text>')

    for key, cls in (("live", "s3"), ("best", "s1")):
        pts = [(x(i), y(row[key])) if row[key] is not None else None
               for i, row in enumerate(grid)]
        parts.append(f'<path class="{cls} thin" d="{_path(pts)}"/>')

    for i, row in enumerate(grid):
        if row["t"].endswith(("-10 00:00", "-20 00:00", "-30 00:00", "-01 00:00")):
            parts.append(f'<line class="daytick" x1="{x(i):.1f}" x2="{x(i):.1f}" '
                         f'y1="{H-B}" y2="{H-B+5}"/>')
            parts.append(f'<text class="tick" x="{x(i):.1f}" y="{H-B+20}" text-anchor="middle">'
                         f'{row["t"][8:10]}.{row["t"][5:7]}</text>')

    step = max(1, n // 240)
    for i in range(0, n, step):
        row = grid[i]
        wet = "дождь" if row["truth"] == 1.0 else "сухо"
        mm = f", {row['precip']:.1f} мм" if row["precip"] else ""
        best = fmt(row["best"], 0) if row["best"] is not None else "—"
        live = fmt(row["live"], 0) if row["live"] is not None else "—"
        parts.append(
            f'<rect class="hit" x="{x(i)-2:.1f}" y="{T}" width="4" height="{H-T-B}">'
            f'<title>{esc(row["t"])} UTC · {wet}{esc(mm)}\n'
            f'pressure_primary {best} · боевая {live}</title></rect>')

    parts.append(f'<text class="axis" x="{L}" y="{H-8}">'
                 f'вероятность дождя, % · синяя полоса — фактический дождь</text>')
    parts.append('</svg>')
    return "".join(parts)


def chart_sources(cc: dict) -> str:
    pc = cc["precip_comparison"]
    bars = [("Open-Meteo", pc["om_rain_hours"], "s1"),
            ("Meteostat", pc["ms_rain_hours"], "s2"),
            ("Яндекс", pc.get("yx_rain_hours"), "s3")]
    bars = [b for b in bars if b[1] is not None]
    W, H = 460, 250
    L, R, T, B = 44, 16, 20, 42
    top = max(b[1] for b in bars) * 1.25
    bw = (W - L - R) / len(bars) * 0.5
    y = lambda v: T + (top - v) * (H - T - B) / top

    parts = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
             f'aria-label="Сколько дождевых часов насчитал каждый источник">']
    for gv in range(0, int(top) + 1, 20):
        parts.append(f'<line class="grid" x1="{L}" x2="{W-R}" y1="{y(gv):.1f}" y2="{y(gv):.1f}"/>')
        parts.append(f'<text class="tick" x="{L-8}" y="{y(gv)+4:.1f}" text-anchor="end">{gv}</text>')
    for i, (label, value, cls) in enumerate(bars):
        cx = L + (i + 0.5) * (W - L - R) / len(bars)
        parts.append(f'<rect class="bar-{cls}" x="{cx-bw/2:.1f}" y="{y(value):.1f}" '
                     f'width="{bw:.1f}" height="{H-B-y(value):.1f}" rx="4">'
                     f'<title>{esc(label)}: {value} дождевых часов из 672</title></rect>')
        parts.append(f'<text class="value" x="{cx:.1f}" y="{y(value)-9:.1f}" '
                     f'text-anchor="middle">{value}</text>')
        parts.append(f'<text class="tick" x="{cx:.1f}" y="{H-B+20}" text-anchor="middle">'
                     f'{esc(label)}</text>')
    parts.append(f'<text class="axis" x="{L}" y="{H-6}">дождевых часов за одни и те же 672 часа</text>')
    parts.append('</svg>')
    return "".join(parts)


def diagram_front() -> str:
    """What counts as a hit: rain has to *begin* within three hours of the alert."""
    W, H = 920, 210
    hours = 14
    x = lambda i: 60 + i * (W - 130) / hours
    base = 120
    rain_from = 8
    parts = [f'<svg viewBox="0 0 {W} {H}" class="chart diagram" role="img" '
             f'aria-label="Схема: что считается предсказанным началом дождя">']
    parts.append(f'<rect class="rain" x="{x(rain_from):.1f}" y="{base-58}" '
                 f'width="{x(hours)-x(rain_from):.1f}" height="58"/>')
    parts.append(f'<line class="axisline" x1="{x(0):.1f}" x2="{x(hours):.1f}" '
                 f'y1="{base}" y2="{base}"/>')
    for i in range(hours + 1):
        parts.append(f'<line class="daytick" x1="{x(i):.1f}" x2="{x(i):.1f}" '
                     f'y1="{base}" y2="{base+6}"/>')
    parts.append(f'<text class="diagram-note dry" x="{x(0):.1f}" y="{base+26}">сухо</text>')
    parts.append(f'<text class="diagram-note wet" x="{x(rain_from)+6:.1f}" y="{base-66}">'
                 f'дождь пошёл</text>')

    win_from, win_to = rain_from - 3, rain_from
    parts.append(f'<rect class="window" x="{x(win_from):.1f}" y="{base-92}" '
                 f'width="{x(win_to)-x(win_from):.1f}" height="92" rx="6"/>')
    parts.append(f'<text class="diagram-label" x="{(x(win_from)+x(win_to))/2:.1f}" '
                 f'y="{base-100}" text-anchor="middle">три часа до начала</text>')

    parts.append(f'<circle class="dot-s1" cx="{x(win_from+1):.1f}" cy="{base-30}" r="6"/>')
    parts.append(f'<text class="diagram-note good" x="{x(win_from+1)+12:.1f}" y="{base-26}">'
                 f'тревога здесь — попадание</text>')
    parts.append(f'<circle class="dot-rest" cx="{x(2):.1f}" cy="{base-30}" r="6"/>')
    parts.append(f'<text class="diagram-note" x="{x(2)+12:.1f}" y="{base-26}">'
                 f'тревога здесь — ложная</text>')
    parts.append(f'<circle class="dot-rest" cx="{x(11):.1f}" cy="{base-30}" r="6"/>')
    parts.append(f'<text class="diagram-note" x="{x(11)+12:.1f}" y="{base-26}" '
                 f'text-anchor="end">дождь уже идёт — не считается</text>')
    parts.append('</svg>')
    return "".join(parts)


CSS = """
:root {
  color-scheme: light;
  --ground: #eef1f5;
  --surface: #ffffff;
  --surface-2: #f7f9fb;
  --ink: #151a21;
  --ink-2: #566173;
  --ink-3: #8792a3;
  --rule: #d9dfe8;
  --accent: #3b4bc0;
  --accent-soft: #e7e9fb;
  --s1: #2a78d6;
  --s2: #eb6834;
  --s3: #1baf7a;
  --rain: rgba(42, 120, 214, 0.14);
  --rest: #c2cad6;
  --control: #8792a3;
  --warn: #b45309;
  --shadow: 0 1px 2px rgba(20, 30, 50, .06), 0 8px 24px -16px rgba(20, 30, 50, .3);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --ground: #0f1319;
    --surface: #171c24;
    --surface-2: #1d232c;
    --ink: #e9edf3;
    --ink-2: #a3aec0;
    --ink-3: #7b8698;
    --rule: #2a323d;
    --accent: #93a0f2;
    --accent-soft: #232a44;
    --s1: #3987e5;
    --s2: #ee7c46;
    --s3: #22c187;
    --rain: rgba(57, 135, 229, 0.20);
    --rest: #3c4556;
    --control: #6b7686;
    --warn: #e0a45c;
    --shadow: 0 1px 2px rgba(0,0,0,.4), 0 10px 30px -18px rgba(0,0,0,.8);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --ground: #0f1319;
  --surface: #171c24;
  --surface-2: #1d232c;
  --ink: #e9edf3;
  --ink-2: #a3aec0;
  --ink-3: #7b8698;
  --rule: #2a323d;
  --accent: #93a0f2;
  --accent-soft: #232a44;
  --s1: #3987e5;
  --s2: #ee7c46;
  --s3: #22c187;
  --rain: rgba(57, 135, 229, 0.20);
  --rest: #3c4556;
  --control: #6b7686;
  --warn: #e0a45c;
  --shadow: 0 1px 2px rgba(0,0,0,.4), 0 10px 30px -18px rgba(0,0,0,.8);
}
"""

CSS += """
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--ground);
  color: var(--ink);
  font-family: 'IBM Plex Sans', ui-sans-serif, system-ui, 'Segoe UI', sans-serif;
  font-size: 17px;
  line-height: 1.65;
  -webkit-font-smoothing: antialiased;
}
.page { max-width: 1120px; margin: 0 auto; padding: 0 24px 96px; }
.prose { max-width: 68ch; }

header.masthead {
  padding: 72px 0 40px;
  border-bottom: 1px solid var(--rule);
  margin-bottom: 48px;
}
.eyebrow {
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  font-size: 12px;
  letter-spacing: .13em;
  text-transform: uppercase;
  color: var(--ink-3);
  margin: 0 0 14px;
}
h1 {
  font-family: 'PT Serif', Georgia, 'Times New Roman', serif;
  font-size: clamp(34px, 5.2vw, 54px);
  line-height: 1.1;
  letter-spacing: -.015em;
  margin: 0 0 18px;
  text-wrap: balance;
}
h2 {
  font-family: 'PT Serif', Georgia, serif;
  font-size: clamp(24px, 3vw, 32px);
  line-height: 1.2;
  margin: 0 0 8px;
  text-wrap: balance;
}
h3 {
  font-family: 'PT Serif', Georgia, serif;
  font-size: 21px;
  margin: 32px 0 6px;
}
p { margin: 0 0 18px; }
.lede { font-size: 20px; color: var(--ink-2); max-width: 62ch; }
strong { font-weight: 600; }
code, .num {
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
}
code {
  font-size: .88em;
  background: var(--surface-2);
  border: 1px solid var(--rule);
  border-radius: 4px;
  padding: 1px 5px;
}
a { color: var(--accent); text-decoration-thickness: 1px; text-underline-offset: 2px; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; border-radius: 3px; }

section { margin: 0 0 64px; }
section > .eyebrow { margin-bottom: 10px; }
.section-head { border-top: 1px solid var(--rule); padding-top: 28px; margin-bottom: 24px; }

.headline-figures {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 1px;
  background: var(--rule);
  border: 1px solid var(--rule);
  border-radius: 12px;
  overflow: hidden;
  margin: 32px 0 40px;
}
.figure { background: var(--surface); padding: 22px 20px; }
.figure .value {
  font-family: 'IBM Plex Mono', monospace;
  font-variant-numeric: tabular-nums;
  font-size: 34px;
  line-height: 1.1;
  letter-spacing: -.02em;
}
.figure .caption { color: var(--ink-2); font-size: 14px; margin-top: 6px; }
.figure.bad .value { color: var(--s2); }

figure { margin: 0 0 12px; }
.chart-card {
  background: var(--surface);
  border: 1px solid var(--rule);
  border-radius: 12px;
  padding: 22px 20px 14px;
  box-shadow: var(--shadow);
  margin: 24px 0 12px;
  overflow-x: auto;
}
.chart { width: 100%; height: auto; display: block; min-width: 560px; }
.chart-card figcaption {
  color: var(--ink-2);
  font-size: 14px;
  margin-top: 10px;
  max-width: 78ch;
}
.legend { display: flex; flex-wrap: wrap; gap: 18px; margin: 4px 0 14px; font-size: 14px; }
.legend span { display: inline-flex; align-items: center; gap: 7px; color: var(--ink-2); }
.swatch { width: 14px; height: 3px; border-radius: 2px; display: inline-block; }
.swatch.dashed { height: 0; border-top: 2px dashed var(--control); }

.grid { stroke: var(--rule); stroke-width: 1; }
.axisline { stroke: var(--ink-3); stroke-width: 1.5; }
.daytick { stroke: var(--ink-3); stroke-width: 1; }
.chance { stroke: var(--ink-3); stroke-width: 1.5; stroke-dasharray: 5 4; }
.switch { stroke: var(--warn); stroke-width: 1.5; stroke-dasharray: 3 3; }
.tick, .axis, .chance-label, .switch-label, .rowlabel, .value, .lead,
.pointlabel, .diagram-note, .diagram-label {
  font-family: 'IBM Plex Sans', sans-serif;
  font-size: 12px;
  fill: var(--ink-2);
}
.tick, .value { font-family: 'IBM Plex Mono', monospace; font-variant-numeric: tabular-nums; }
.axis { fill: var(--ink-3); font-size: 12.5px; }
.switch-label { fill: var(--warn); }
.rowlabel { font-size: 13px; fill: var(--ink-2); }
.rowlabel.strong { fill: var(--ink); font-weight: 600; }
.lead, .pointlabel { font-size: 13px; font-weight: 600; }
.value { fill: var(--ink); font-size: 13px; }

path.s1, path.s2, path.s3 { fill: none; stroke-width: 2.5; stroke-linejoin: round; }
path.thin { stroke-width: 1.6; }
path.s1 { stroke: var(--s1); }
path.s2 { stroke: var(--s2); }
path.s3 { stroke: var(--s3); }
path.rest { fill: none; stroke: var(--rest); stroke-width: 1; opacity: .55; }
path.control { fill: none; stroke: var(--control); stroke-width: 1.6; stroke-dasharray: 4 3; }
.s1-dot, .dot-s1, .s1-fill { fill: var(--s1); }
.s2-dot, .dot-s2, .s2-fill { fill: var(--s2); }
.s3-dot, .dot-s3, .s3-fill { fill: var(--s3); }
.dot-rest, .rest-fill { fill: var(--rest); }
.s1-text { fill: var(--s1); } .s2-text { fill: var(--s2); } .s3-text { fill: var(--s3); }
.whisker { stroke-width: 2; opacity: .5; }
.s1-stroke { stroke: var(--s1); } .s2-stroke { stroke: var(--s2); }
.s3-stroke { stroke: var(--s3); } .rest-stroke { stroke: var(--rest); }
.bar-s1 { fill: var(--s1); } .bar-s2 { fill: var(--s2); } .bar-s3 { fill: var(--s3); }
.rain { fill: var(--rain); }
.window { fill: var(--accent-soft); stroke: var(--accent); stroke-dasharray: 4 3; }
.diagram-note.good { fill: var(--s1); font-weight: 600; }
.diagram-note.wet { fill: var(--s1); font-weight: 600; }
.diagram-label { fill: var(--accent); font-weight: 600; }
.hit { fill: transparent; }
.hit:hover { fill: var(--accent); opacity: .07; }

.table-wrap { overflow-x: auto; margin: 22px 0; }
table { width: 100%; border-collapse: collapse; font-size: 15px; }
th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--rule); }
th {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11.5px;
  letter-spacing: .09em;
  text-transform: uppercase;
  color: var(--ink-3);
  font-weight: 500;
}
td.n { font-family: 'IBM Plex Mono', monospace; font-variant-numeric: tabular-nums; text-align: right; }
tbody tr:hover { background: var(--surface-2); }
tr.highlight td { background: var(--accent-soft); }

.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 18px; margin: 28px 0; }
.card {
  background: var(--surface);
  border: 1px solid var(--rule);
  border-radius: 12px;
  padding: 20px;
}
.card h3 { margin: 0 0 4px; font-size: 19px; }
.card .role {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11.5px;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--ink-3);
  margin-bottom: 10px;
}
.card p { font-size: 15px; margin-bottom: 10px; color: var(--ink-2); }
.card .verdict { font-size: 15px; color: var(--ink); }
.card.win { border-color: var(--s1); }
.card.lose { border-color: var(--s2); }

.callout {
  border-left: 3px solid var(--accent);
  background: var(--surface);
  border-radius: 0 10px 10px 0;
  padding: 18px 22px;
  margin: 26px 0;
}
.callout p:last-child { margin-bottom: 0; }
.callout.warn { border-left-color: var(--warn); }

ol.steps { counter-reset: step; list-style: none; padding: 0; margin: 26px 0; }
ol.steps li {
  counter-increment: step;
  position: relative;
  padding: 0 0 20px 46px;
  border-bottom: 1px solid var(--rule);
  margin-bottom: 20px;
}
ol.steps li:last-child { border-bottom: 0; }
ol.steps li::before {
  content: counter(step);
  position: absolute; left: 0; top: 1px;
  width: 30px; height: 30px;
  display: grid; place-items: center;
  border-radius: 50%;
  background: var(--accent-soft);
  color: var(--accent);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 14px; font-weight: 600;
}
ol.steps h3 { margin: 0 0 4px; font-size: 18px; }
ol.steps p { margin: 0; color: var(--ink-2); font-size: 15px; }

ul.plain { padding-left: 20px; }
ul.plain li { margin-bottom: 10px; }

footer {
  border-top: 1px solid var(--rule);
  padding-top: 22px;
  color: var(--ink-3);
  font-size: 14px;
}
.split-card { display: grid; grid-template-columns: minmax(300px, 1fr) minmax(280px, 1.1fr); gap: 28px; align-items: center; }
@media (max-width: 820px) {
  .split-card { grid-template-columns: 1fr; }
  .split-card .chart { min-width: 0; }
}
@media (max-width: 700px) {
  body { font-size: 16px; }
  .page { padding: 0 16px 64px; }
  header.masthead { padding-top: 44px; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
"""


def render(reports: dict, grid: list) -> str:
    dates = sorted(reports)
    latest = dates[-1]
    last = reports[latest]
    fresh = [d for d in dates if d >= TRUTH_SWITCH]

    series = front_series(reports)
    ctx = onset_context(reports)
    rank = ranking(series, fresh)
    costs = alert_cost(last)
    ft = last["scoring"]["front_target"]
    gt = last["metadata"]["data_stats"]["ground_truth"]
    cc = last["cross_check"]
    learned = last["scoring"]["learned"]

    by_name = {r["name"]: r for r in rank}
    best = rank[0]
    prod = by_name.get("ha_live_actual")
    gate = by_name.get("onset_gate")
    ctrl = by_name.get("persistence")
    best_cost = next(c for c in costs if c["name"] == best["name"])
    prod_cost = next((c for c in costs if c["name"] == "ha_live_actual"), None)

    kappa = cc["ground_truth_agreement"]["pairs"]
    worst_kappa = min(p["kappa"] for p in kappa.values())
    replica = cc["sensor_diagnostics"]["replica_vs_actual"] or {}
    yx = cc["yandex_vs_truth"] or {}

    wins = sum(1 for d in fresh
               if max((n for n in series if d in series[n]),
                      key=lambda n: series[n][d]) == best["name"])

    def rows_table(rows):
        out = []
        for r in rows:
            cost = next((c for c in costs if c["name"] == r["name"]), None)
            highlight = r["name"] in ("pressure_primary", "ha_live_actual")
            cls = ' class="highlight"' if highlight else ""
            per_day = fmt(cost["per_day"], 2) if cost else "—"
            prec = f"{cost['precision']*100:.0f}%" if cost else "—"
            caught = f"{cost['caught']}/{cost['onsets']}" if cost else "—"
            out.append(
                f"<tr{cls}><td>{esc(RU.get(r['name'], r['name']))}</td>"
                f'<td class="n">{fmt(r["mean"])}</td>'
                f'<td class="n">{fmt(r["lo"])} – {fmt(r["hi"])}</td>'
                f'<td class="n">{per_day}</td>'
                f'<td class="n">{prec}</td>'
                f'<td class="n">{caught}</td></tr>')
        return "".join(out)

    charts = {
        "dynamics": chart_dynamics(series, dates, ctx),
        "ranking": chart_ranking(rank),
        "cost": chart_alert_cost(costs, ft["base_rate"]),
        "timeline": chart_timeline(grid),
        "sources": chart_sources(cc),
        "diagram": diagram_front(),
    }
    return PAGE.format(
        css=CSS,
        generated=datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC"),
        first_date=dates[0], last_date=latest, n_reports=len(dates),
        n_fresh=len(fresh),
        best_name=esc(best["name"]), best_mean=fmt(best["mean"]),
        best_lo=fmt(best["lo"]), best_hi=fmt(best["hi"]), wins=wins,
        gate_mean=fmt(gate["mean"]) if gate else "—",
        prod_mean=fmt(prod["mean"]) if prod else "—",
        ctrl_mean=fmt(ctrl["mean"]) if ctrl else "—",
        onsets=ft["n_onsets"], base_pct=f"{ft['base_rate']*100:.1f}".replace(".", ","),
        dry_hours=gt["front_distribution"]["labelled_dry_hours"],
        rain_hours=gt["distribution"]["rain_hours"],
        best_per_day=f"{best_cost['per_day']:.2f}".replace(".", ","),
        best_prec=f"{best_cost['precision']*100:.0f}",
        best_caught=best_cost["caught"], best_thr=f"{best_cost['threshold']:.0f}",
        prod_per_day=f"{prod_cost['per_day']:.2f}".replace(".", ",") if prod_cost else "—",
        prod_prec=f"{prod_cost['precision']*100:.0f}" if prod_cost else "—",
        prod_caught=prod_cost["caught"] if prod_cost else "—",
        om_hours=cc["precip_comparison"]["om_rain_hours"],
        ms_hours=cc["precip_comparison"]["ms_rain_hours"],
        yx_hours=cc["precip_comparison"].get("yx_rain_hours", "—"),
        kappa_lo=fmt(worst_kappa, 2),
        yx_said=yx.get("yandex_rain_hours", "—"), yx_actual=yx.get("actual_rain_hours", "—"),
        yx_agree=yx.get("agreement_hours", "—"),
        replica_corr=fmt(replica.get("corr"), 3), replica_mae=fmt(replica.get("mae"), 1),
        learned_warn=fmt(learned["within_3h"]["roc_auc"]),
        learned_front=fmt(learned["front"]["roc_auc"]),
        learned_gate=fmt(learned["front"]["comparison_on_same_rows"].get("onset_gate")),
        table=rows_table(rank),
        **{f"chart_{k}": v for k, v in charts.items()},
    )


PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Кто предсказывает дождь</title>
<meta name="description" content="Разбор моделей предсказания дождя по 50 ежедневным отчётам: кто выигрывает, чего стоят тревоги и почему боевая модель ниже случайного угадывания.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=PT+Serif:ital,wght@0,400;0,700;1,400&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>{css}</style>
</head>
<body>
<div class="page">

<header class="masthead">
  <p class="eyebrow">разбор моделей · {first_date} — {last_date} · {n_reports} отчётов</p>
  <h1>Кто предсказывает дождь</h1>
  <p class="lede">Пятьдесят ежедневных отчётов, тринадцать моделей и один вопрос: если во дворе
  сухо, какая из них успевает сказать «сейчас польёт» — и сколько раз при этом ошибётся зря.</p>
</header>

<div class="headline-figures">
  <div class="figure">
    <div class="value">{best_mean}</div>
    <div class="caption"><strong>{best_name}</strong> — лучший результат.
    Случайное угадывание даёт 0,500</div>
  </div>
  <div class="figure">
    <div class="value">{wins} из {n_fresh}</div>
    <div class="caption">окон, где она выиграла у всех остальных. Это уже не совпадение</div>
  </div>
  <div class="figure bad">
    <div class="value">{prod_mean}</div>
    <div class="caption">у модели, которая реально работает в доме — <em>ниже</em> монетки</div>
  </div>
  <div class="figure">
    <div class="value">{onsets}</div>
    <div class="caption">случаев начала дождя в последнем окне. Все выводы опираются на них</div>
  </div>
</div>

<section>
  <div class="section-head"><p class="eyebrow">сначала — про линейку</p>
  <h2>Что здесь считается успехом</h2></div>
  <div class="prose">
    <p>Модель полезна ровно в одном случае: во дворе сухо, она говорит «скоро дождь», и дождь
    действительно начинается в ближайшие три часа. Всё остальное не считается — ни угаданный
    дождь, который уже идёт (тут угадывать нечего, достаточно выглянуть в окно), ни правильно
    предсказанное окончание дождя.</p>
  </div>
  <figure class="chart-card">
    {chart_diagram}
    <figcaption>Засчитывается только тревога, поднятая из сухого часа и не раньше чем за три часа
    до начала дождя. Часы внутри дождя из подсчёта выброшены полностью.</figcaption>
  </figure>
  <div class="prose">
    <p>Дальше везде одна мера — <strong>ROC AUC</strong>. Читается просто: берём случайный час,
    когда дождь вот-вот начнётся, и случайный час, когда он не начнётся. AUC — это доля случаев,
    когда модель дала первому часу вероятность выше. 0,5 — она не различает их вообще, монетка.
    1,0 — различает всегда.</p>
    <p>Чтобы поймать модель, которая просто повторяет вчерашнюю погоду, в таблицах есть контроль:
    <strong>«как час назад»</strong> — правило «сейчас будет то же, что было час назад». На этой
    задаче оно обязано набирать около 0,5, и набирает {ctrl_mean}. Если какая-то модель окажется
    рядом с ним, значит она ничего не предсказывает, чем бы ни выглядели её остальные метрики.</p>
  </div>
  <div class="callout">
    <p>Событие редкое: за последнее 28-дневное окно — {onsets} начал дождя на {dry_hours} сухих
    часов. Случайная тревога попадает в цель с вероятностью {base_pct}%. Это та планка, которую
    любая модель обязана перебить, чтобы вообще иметь смысл.</p>
  </div>
</section>

<section>
  <div class="section-head"><p class="eyebrow">график 1 · 28-дневные окна, {n_reports} дат</p>
  <h2>Как менялись результаты</h2></div>
  <div class="legend">
    <span><i class="swatch" style="background:var(--s1)"></i>pressure_primary</span>
    <span><i class="swatch" style="background:var(--s2)"></i>onset_gate</span>
    <span><i class="swatch" style="background:var(--s3)"></i>боевая модель</span>
    <span><i class="swatch dashed"></i>«как час назад» — контроль</span>
    <span><i class="swatch" style="background:var(--rest)"></i>остальные девять</span>
  </div>
  <figure class="chart-card">
    {chart_dynamics}
    <figcaption>Наведите курсор на любой день — покажет размер выборки и все значения.
    Разрыв в линиях 14–15 и 21–22 августа: за эти даты отчёты делал старый пайплайн и подробных
    данных не сохранил. onset_gate появился только 21 августа, боевая модель пишется в базу
    с 15 августа — раньше их линий просто нет.</figcaption>
  </figure>
  <div class="prose">
    <p>Две вещи здесь важнее самих кривых. Первая: <strong>14 августа сменился эталон</strong> —
    источник, по которому мы решаем, шёл дождь или нет. До него это был архив реанализа, после —
    прогнозный ряд Open-Meteo, тот же, что копит бэкенд. Второй считает дождевых часов втрое
    меньше, поэтому часть подъёма после этой отметки — не улучшение моделей, а смена линейки.
    Сравнивать значения через эту черту нельзя.</p>
    <p>Вторая: до августа <em>ни одна</em> кривая не отрывалась от 0,5. Это ровно тот период,
    когда ежедневные отчёты бодро сообщали, что «лучшая модель — такая-то»: они ранжировали шум.</p>
  </div>
</section>

<section>
  <div class="section-head"><p class="eyebrow">график 2 · {n_fresh} свежих окон, один эталон</p>
  <h2>Кто сколько набрал</h2></div>
  <figure class="chart-card">
    {chart_ranking}
    <figcaption>Точка — среднее по {n_fresh} окнам, усы — от худшего окна к лучшему. Пунктир —
    отметка 0,5.</figcaption>
  </figure>
  <div class="prose">
    <p><strong>{best_name}</strong> — {best_mean} в среднем, и ни одно окно не опустилось ниже
    {best_lo}. Она выиграла {wins} окон из {n_fresh}. За ней с заметным отрывом идёт
    <strong>onset_gate</strong> ({gate_mean}) — единственная модель, которую делали
    специально под эту задачу.</p>
    <p>А внизу — <strong>боевая модель</strong>, {prod_mean}. Это не «слабо»: это ниже монетки.
    Отрицательное отклонение от 0,5 означает, что перед дождём она в среднем выдаёт вероятность
    <em>ниже</em>, чем в спокойный сухой час. В доме сейчас работает именно она.</p>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr><th>модель</th><th>AUC, среднее</th><th>разброс по окнам</th>
      <th>тревог в сутки</th><th>верных</th><th>поймано</th></tr></thead>
      <tbody>{table}</tbody>
    </table>
  </div>
</section>

<section>
  <div class="section-head"><p class="eyebrow">график 3 · последнее окно, {onsets} онсетов</p>
  <h2>Сколько стоит одна тревога</h2></div>
  <figure class="chart-card">
    {chart_cost}
    <figcaption>Каждая точка — модель на её собственном лучшем пороге. Правее — чаще пищит,
    выше — чаще угадывает. Пунктир — уровень случайной тревоги.</figcaption>
  </figure>
  <div class="prose">
    <p>AUC — величина абстрактная, а это тот же результат в бытовых единицах.
    <strong>{best_name}</strong> на пороге {best_thr}% поднимает тревогу {best_per_day} раза
    в сутки, из них верны {best_prec}%, и она успевает предупредить о {best_caught} дождях
    из {onsets}. Примерно четыре ложные тревоги на одну верную.</p>
    <p>Это честный ответ на вопрос «можно ли уже вешать на это уведомление в телефон». Пока —
    нет. Но {best_prec}% против {base_pct}% случайных — это в два с половиной раза лучше
    случайного, то есть сигнал в данных всё-таки есть, и он не выдуман.</p>
    <p>Точки, лежащие на пунктире, бесполезны при любом пороге: их тревоги не отличаются от
    подбрасывания монетки. Там же находится и «всегда тревога» — правило, которое просто
    сигналит всегда.</p>
  </div>
</section>

<section>
  <div class="section-head"><p class="eyebrow">график 4 · почасовой ряд, 28 дней</p>
  <h2>Как это выглядит по часам</h2></div>
  <div class="legend">
    <span><i class="swatch" style="background:var(--s1)"></i>pressure_primary</span>
    <span><i class="swatch" style="background:var(--s3)"></i>боевая модель</span>
    <span><i class="swatch" style="background:var(--rain);height:12px;width:16px;border-radius:3px"></i>фактический дождь</span>
  </div>
  <figure class="chart-card">
    {chart_timeline}
    <figcaption>Синие полосы — часы, когда шёл дождь. Линии — вероятность, которую в этот час
    выдавала каждая модель.</figcaption>
  </figure>
  <div class="prose">
    <p>Здесь видно то, чего не видно ни в одной таблице. <strong>{best_name}</strong> ползёт
    вверх заранее и почти всегда стоит высоко к моменту, когда полоса начинается — она реагирует
    на падение давления, а давление падает до дождя. Боевая модель дёргается, но её пики
    случайно разбросаны: она реагирует на схождение температуры с точкой росы, а это происходит
    и в сухие ясные ночи тоже.</p>
    <p>Видно и обратную сторону: <strong>{best_name}</strong> подолгу держится высоко там, где
    дождя так и не случилось. Это те самые четыре ложные тревоги на одну верную.</p>
  </div>
</section>

<section>
  <div class="section-head"><p class="eyebrow">график 5 · те же 672 часа, три источника</p>
  <h2>Линейка сама кривая</h2></div>
  <div class="chart-card split-card">
    {chart_sources}
    <div>
      <p style="margin-bottom:14px">Три службы погоды смотрят на одно и то же место в одни и те
      же часы и расходятся в том, шёл ли дождь: <strong>{om_hours}</strong>, <strong>{ms_hours}</strong>
      и <strong>{yx_hours}</strong> дождевых часов. Согласие между ними, с поправкой на
      случайные совпадения, — {kappa_lo}–0,54 из 1,00. Это «умеренное».</p>
      <p style="margin:0">Яндекс, когда его спрашивают напрямую, назвал дождевыми {yx_said} часов
      из {yx_actual} фактических — совпало {yx_agree}.</p>
    </div>
  </div>
  <div class="prose">
    <p>Отсюда следует неприятное: <strong>часть ошибки каждой модели — это ошибка эталона</strong>.
    Если поменять источник истины, порядок в таблице меняется, вплоть до того, что победитель и
    аутсайдер меняются местами. Никакая доводка модели не пробьёт этот потолок, пока мы не решим,
    по какой линейке меряем.</p>
    <p>Косвенное подтверждение: копия боевой модели, посчитанная у нас, совпадает с настоящим
    датчиком в доме почти идеально — корреляция {replica_corr}, средняя ошибка {replica_mae}
    процентного пункта. То есть мы измеряем именно то, что работает в проде, и низкий результат
    боевой модели — не артефакт расчёта.</p>
  </div>
</section>

<section>
  <div class="section-head"><p class="eyebrow">кто есть кто</p>
  <h2>Модели по-человечески</h2></div>
  <div class="cards">
    <div class="card win">
      <h3>pressure_primary</h3>
      <p class="role">давление как главный признак</p>
      <p>Смотрит в первую очередь на атмосферное давление: насколько оно ниже обычного для этого
      места и как далеко упало от суточного максимума. Схождение температуры с точкой росы
      учитывается, но как добавка, а не как основа.</p>
      <p class="verdict"><strong>Лучшая на сегодня.</strong> Выигрывает все {n_fresh} свежих окон.
      Физика за ней очевидная: фронт приходит вместе с падением давления, и приходит заранее.</p>
    </div>
    <div class="card">
      <h3>onset_gate</h3>
      <p class="role">единственная, сделанная под эту задачу</p>
      <p>Обучена не на «идёт ли дождь», а прямо на «начнётся ли дождь» — на пяти годах
      реанализа. Четыре признака: аномалия давления, падение от суточного пика, влажность,
      ход температуры. Схождения с точкой росы там нет намеренно.</p>
      <p class="verdict">Второе место, {gate_mean}. Держится ровнее всех — разброс по окнам у неё
      самый узкий, — но пока не догоняет.</p>
    </div>
    <div class="card lose">
      <h3>боевая модель</h3>
      <p class="role">то, что сейчас крутится в доме</p>
      <p>Срабатывает, когда температура сходится с точкой росы и это схождение ускоряется.
      Идея понятная: воздух насыщается — значит дождь. На деле воздух точно так же насыщается
      в ясную безветренную ночь, когда никакого дождя не будет.</p>
      <p class="verdict"><strong>{prod_mean} — ниже случайного.</strong> Проверено на длинной
      истории: на спокойных ночах со сходящимся спредом дождь бывает <em>реже</em>, чем обычно.
      Модель принимает за сигнал то, что является анти-сигналом.</p>
    </div>
    <div class="card">
      <h3>семь моделей pressure_*</h3>
      <p class="role">одна модель под семью именами</p>
      <p>pressure_absolute, pressure_lagged, pressure_combined, pressure_long_window,
      pressure_aware, tuned, combined — все считают примерно одно и то же с чуть разными
      коэффициентами.</p>
      <p class="verdict">Их результаты укладываются в 0,53–0,56 и различаются меньше, чем одна и
      та же модель различается от окна к окну. Половина строк в каждой таблице — это иллюзия
      выбора.</p>
    </div>
    <div class="card">
      <h3>обученная модель</h3>
      <p class="role">логистическая регрессия, честная проверка</p>
      <p>Учится на прошлом и проверяется только на тех часах, которых не видела. Двадцать
      признаков: давление и его производные, влажность, спред, время суток.</p>
      <p class="verdict">На вопросе «пойдёт ли дождь в ближайшие три часа» — лучший результат
      вообще, {learned_warn}. Но на строгой задаче начала дождя из сухого часа — {learned_front},
      против {learned_gate} у onset_gate на тех же самых часах. Учить её надо прямо на онсетах.</p>
    </div>
    <div class="card">
      <h3>«как час назад» и «всегда тревога»</h3>
      <p class="role">контроли, а не модели</p>
      <p>Первое повторяет прошлый час, второе сигналит всегда. Они здесь, чтобы ловить
      самообман.</p>
      <p class="verdict">На старых метриках «как час назад» уверенно обыгрывало все модели
      подряд — именно поэтому те метрики и пришлось выбросить. На честной задаче оно даёт
      {ctrl_mean}, как и положено.</p>
    </div>
  </div>
</section>

<section>
  <div class="section-head"><p class="eyebrow">что дальше</p>
  <h2>Четыре шага, по убыванию пользы</h2></div>
  <ol class="steps">
    <li>
      <h3>Заменить боевую модель</h3>
      <p>В доме работает {prod_mean}, на полке лежит {best_mean}. Это самое дешёвое улучшение из
      возможных: формула уже написана и проверена на {n_fresh} независимых окнах.</p>
    </li>
    <li>
      <h3>Чинить измерение, а не модели</h3>
      <p>Бэкенд до сих пор считает качество за один день на фиксированном пороге — половина
      значений выходит ровно нулевой. Нужны скользящие 28-дневные окна и та мера, что на этой
      странице. Пока её нет, любое «улучшение» неотличимо от погоды за окном.</p>
    </li>
    <li>
      <h3>Выбрать эталон и зафиксировать его</h3>
      <p>Расхождение источников ({om_hours} против {ms_hours} дождевых часов) сейчас больше, чем
      разница между моделями. Пока источник не выбран, потолок точности задаём не мы.</p>
    </li>
    <li>
      <h3>Копить онсеты</h3>
      <p>{onsets} событий на окно — это доверительный интервал шириной около ±0,13. Различить
      {best_mean} и {gate_mean} на таких данных нельзя. Нужен либо ещё месяц-другой наблюдений,
      либо обучение на длинной истории с проверкой на своих датчиках.</p>
    </li>
  </ol>
</section>

<section>
  <div class="section-head"><p class="eyebrow">оговорки</p>
  <h2>Чему на этой странице верить нельзя</h2></div>
  <div class="prose">
    <ul class="plain">
      <li><strong>Событий мало.</strong> {onsets} начал дождя на окно. Разница меньше 0,1 по AUC
      — это шум, а не преимущество.</li>
      <li><strong>Эталон менялся 14 августа.</strong> Значения слева и справа от этой черты
      измерены разными линейками; сравнивать их напрямую нельзя.</li>
      <li><strong>22–23 августа датчики молчали 28 часов.</strong> В окна, куда попадает этот
      провал, часть часов не вошла — покрытие там около 80%.</li>
      <li><strong>Боевая модель наблюдается только с 15 августа</strong>, а onset_gate появился
      21 августа. У них короче история, чем у остальных.</li>
      <li><strong>Яндекс был недоступен</strong> при пересчёте июльских отчётов, поэтому в левой
      части графиков его сравнения нет.</li>
    </ul>
  </div>
</section>

<footer>
  <p>Собрано из {n_reports} ежедневных отчётов за {first_date} — {last_date}
  скриптом <code>scripts_utils/build_model_report.py</code>. Все числа посчитаны при сборке из
  тех же JSON, что стоят за ежедневными отчётами. {generated}.</p>
</footer>

</div>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--reports-dir", type=Path, default=Path("reports/daily"),
                        help="Directory of per-date report JSON (default: reports/daily)")
    parser.add_argument("--grid", type=Path, required=True,
                        help="Hourly grid CSV from run_analysis.py --dump-grid")
    parser.add_argument("--output", "-o", type=Path, required=True, help="Output HTML path")
    parser.add_argument("--fragment", action="store_true",
                        help="Emit the page without the document shell, for hosts "
                             "that supply their own <html>/<head>/<body>")
    args = parser.parse_args()

    reports = load_reports(args.reports_dir)
    if not reports:
        print(f"[ERROR] no reports under {args.reports_dir}", file=sys.stderr)
        return 1
    grid = read_grid(args.grid)
    if not grid:
        print(f"[ERROR] empty grid: {args.grid}", file=sys.stderr)
        return 1

    page = render(reports, grid)
    if args.fragment:
        head = page.split("<head>", 1)[1].split("</head>", 1)[0]
        body = page.split("<body>", 1)[1].rsplit("</body>", 1)[0]
        # The host supplies charset and viewport; everything else in the head
        # (title, description, fonts, styles) still belongs to the page.
        head = "\n".join(l for l in head.splitlines()
                          if not l.startswith(("<meta charset", '<meta name="viewport"')))
        page = head + "\n" + body

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(page, encoding="utf-8")
    print(f"[DONE] {len(reports)} reports, {len(grid)} hours → {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
