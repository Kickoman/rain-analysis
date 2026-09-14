#!/usr/bin/env python3
"""
score_alert_rules.py — what the notifications that actually fire are worth.
==========================================================================

Every other scorer here measures *models*. This measures the two Home
Assistant automations that actually send a Telegram message, on the target
that matters: from a dry hour, did the message arrive before rain began?

They are not the same thing as `sensor.rain_probability`, which drives no
notification at all — so "the deployed sensor is at chance" and "your alerts
are at chance" are separate claims, and only this answers the second.

The rules are transcribed from automations.yaml / templates.yaml; keep them in
step by hand when the automations change, and say so in the output when they
are edited. Run from the repo root.
"""
import sys
sys.path.insert(0, "analysis"); sys.path.insert(0, ".")
import numpy as np, pandas as pd
import rainlib as rl
from run_analysis import AnalysisConfig, load_data, compute_features, run_models
sys.path.insert(0, "scripts_utils")
from pressure_variants import pressure_anomaly

cfg = AnalysisConfig(ha_csv="data/archive/ha_hourly.csv",
    om_sources=["data/archive/om_backfill_forecast.json"],
    meteostat_json="data/archive/ms_backfill.json",
    window_start="2026-07-18T00:00:00+00:00", window_end="2026-09-14T22:00:00+00:00",
    learned_model=False)
grid, _ = load_data(cfg); grid = compute_features(grid, cfg); grid, _ = run_models(grid, cfg)
t = rl.label_rain(grid, "om_precip", 0.1)
grid["rain_truth"] = t
onsets = grid.index[rl.detect_onsets(t, 3) == 1]
dry = t == 0
step = pd.Timedelta("1h")
days = len(grid) / 24

spread = grid["ha_spread"].fillna(grid["spread"])
trend = grid["ha_spread_trend"].fillna(grid["spread_deriv"])
anomaly = pressure_anomaly(grid["pressure"])
rh = grid["rh"]

# Transcribed from the running configuration on 2026-09-15.
possible_rain = (spread < 4) & (trend < -0.5)      # automation "Possible rain notification"
rain_likely = (anomaly < -3) & (rh > 75)           # binary_sensor.rain_likely
rules = {
    "'Possible rain' (spread<4 & trend<-0.5)": possible_rain,
    "'Rain likely' (anomaly<-3 & rh>75)": rain_likely,
    "either of the two": possible_rain | rain_likely,
    "pressure_primary >= 80 (proposed)": grid["model_pressure_primary"] >= 80,
}

print(f"record {days:.0f} days, {len(onsets)} onsets, {int(dry.sum())} dry hours\n")
print(f"{'rule':42s} {'catches':>8s} {'if random':>10s} {'lift':>5s} {'h/wk':>5s} {'lead':>5s}")
for name, alert_raw in rules.items():
    alert = alert_raw.fillna(False) & dry
    n = int(alert.sum())
    if n == 0:
        print(f"{name:42s} {'never fires':>8s}")
        continue
    hits, leads = 0, []
    for o in onsets:
        fired = [k for k in (1, 2, 3)
                 if (o - step*k) in alert.index and bool(alert.loc[o - step*k])]
        if fired:
            hits += 1; leads.append(max(fired))
    share = n / float(dry.sum())
    exp = (1 - (1 - share) ** 3) * len(onsets)
    lo, hi = rl.wilson_interval(hits, len(onsets))
    print(f"{name:42s} {str(hits)+'/'+str(len(onsets)):>8s} {exp:10.1f} "
          f"{hits/exp if exp else 0:5.2f} {n/days*7:5.0f} "
          f"{np.median(leads) if leads else 0:5.1f}   95% CI {lo*100:.0f}-{hi*100:.0f}%")
