#!/usr/bin/env python3
"""
validate_on_reanalysis.py — check the onset ranking on 50x more events.
=======================================================================

The local record buys 29 rain onsets per two months, and the daily report's
confidence intervals say plainly that this cannot separate two models a few
points apart. This scores the same candidates on years of Open-Meteo reanalysis
at the project's coordinates — over a thousand onsets — to ask a narrower but
much better-powered question: does the signal each model uses predict the start
of rain *at all*, and is the ordering stable from year to year?

Stated up front, because it bounds every number below: **reanalysis is not
these sensors.** It smooths convective showers over an ~11 km cell, and its
humidity is a model field rather than this balcony. So this answers "is the
skill real", not "what would the alert have done here". The daily report,
scored on local sensors against local ground truth, remains the thing that
decides what to deploy.

Usage:
  python analysis/validate_on_reanalysis.py --start 2021-01-01 --end 2026-06-30
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
# Both: `analysis/` so `import rainlib` finds the real module, and the repo root
# so the lazily-imported pressure variants can `import analysis.rainlib`.
sys.path.insert(0, str(REPO / "analysis"))
sys.path.insert(0, str(REPO))

import rainlib as rl  # noqa: E402
from rainlib import MODELS, ModelContext, ModelParams  # noqa: E402

LAT, LON = 53.930716, 27.596646
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"


def fetch(start: str, end: str, cache: Path) -> dict:
    if cache.exists():
        return json.loads(cache.read_text())
    url = (f"{ARCHIVE}?latitude={LAT}&longitude={LON}"
           f"&start_date={start}&end_date={end}"
           "&hourly=temperature_2m,relative_humidity_2m,surface_pressure,precipitation"
           "&timezone=UTC")
    with urllib.request.urlopen(url, timeout=300) as response:
        payload = json.load(response)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload))
    return payload


def build(payload: dict) -> pd.DataFrame:
    h = payload["hourly"]
    df = pd.DataFrame({
        "temp": h["temperature_2m"],
        "rh": h["relative_humidity_2m"],
        "pressure": h["surface_pressure"],
        "precip": h["precipitation"],
    }, index=pd.to_datetime(h["time"], utc=True)).dropna(subset=["temp", "rh", "pressure"])
    df["spread"] = rl.dew_point_spread(df["temp"], df["rh"])
    df["spread_deriv"] = rl.derivative(df["spread"], window="3h")
    df["abs_humidity"] = rl.absolute_humidity(df["temp"], df["rh"])
    return df


def context(df: pd.DataFrame) -> ModelContext:
    return ModelContext(spread=df["spread"], spread_deriv=df["spread_deriv"],
                        abs_humidity=df["abs_humidity"], temp=df["temp"],
                        pressure=df["pressure"], ha_spread_trend=None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--end", default="2026-06-30")
    parser.add_argument("--cache", default=str(REPO / "data/archive/era5_validation.json"))
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--dry-hours", type=int, default=3)
    args = parser.parse_args()

    df = build(fetch(args.start, args.end, Path(args.cache)))
    labels = (df["precip"] >= 0.1).astype(float)
    labels[df["precip"].isna()] = np.nan
    front = rl.label_front_within(labels, args.horizon, args.dry_hours, freq="1h")
    dry = labels == 0
    onsets = int(rl.detect_onsets(labels, args.dry_hours).sum())

    print(f"{len(df)} hours, {df.index[0].date()} → {df.index[-1].date()}")
    print(f"{onsets} onsets, {int(dry.sum())} dry hours, "
          f"front base rate {front.mean():.3f}\n")

    params = ModelParams()
    ctx = context(df)
    rows = []
    for name, fn in MODELS.items():
        try:
            score = pd.Series(fn(ctx, params)).reindex(df.index).where(dry)
        except Exception as exc:                     # a variant that cannot run here
            print(f"  {name}: skipped ({exc})", file=sys.stderr)
            continue
        mask = score.notna() & front.notna()
        if mask.sum() < 500:
            continue
        lo, hi = rl.bootstrap_auc_ci(score[mask], front[mask], n_boot=120, seed=1)
        rows.append((name, rl.roc_auc(score[mask], front[mask]), lo, hi, int(mask.sum())))

    # The control: a yardstick that rates "it rained an hour ago" as skilful at
    # predicting rain *starts* is measuring the wrong thing.
    pers = (labels.shift(1) * 100.0).where(dry)
    mask = pers.notna() & front.notna()
    lo, hi = rl.bootstrap_auc_ci(pers[mask], front[mask], n_boot=120, seed=1)
    rows.append(("persistence (control)", rl.roc_auc(pers[mask], front[mask]),
                 lo, hi, int(mask.sum())))

    rows.sort(key=lambda r: -(r[1] or 0))
    print(f"{'candidate':24s} {'front AUC':>9s} {'95% CI':>16s} {'dry hours':>10s}")
    for name, auc, lo, hi, n in rows:
        ci = f"[{lo:.3f},{hi:.3f}]" if lo is not None else "—"
        print(f"{name:24s} {auc:9.3f} {ci:>16s} {n:10d}")

    print("\nper-year, to show it is not one lucky season:")
    watch = [n for n in ("onset_gate", "pressure_primary", "ha_live") if n in MODELS]
    print(f"{'year':6s} {'onsets':>7s} " + " ".join(f"{w[:16]:>16s}" for w in watch))
    for year, index in df.groupby(df.index.year).groups.items():
        sub = df.loc[index]
        lab, fr = labels.loc[index], front.loc[index]
        sub_dry = lab == 0
        cells = []
        for name in watch:
            score = pd.Series(MODELS[name](context(sub), params)).reindex(sub.index).where(sub_dry)
            mask = score.notna() & fr.notna()
            cells.append(f"{rl.roc_auc(score[mask], fr[mask]):16.3f}"
                         if mask.sum() > 300 else f"{'—':>16s}")
        print(f"{year:<6d} {int(rl.detect_onsets(lab, args.dry_hours).sum()):7d} "
              + " ".join(cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
