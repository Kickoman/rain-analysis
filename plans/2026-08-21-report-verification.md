# Verification of the 2026-08-14 … 08-21 daily reports

_2026-08-21. Every number below was reproduced from raw sources (HA statistics
API, Open-Meteo, Meteostat), not taken from the reports._

## What was checked and what held

**The 7-day leaderboards were correct.** Rerunning the committed 2026-08-21
report's 7d window on the same recorder data reproduced its F1/precision/recall
to three decimals for 11 of 12 models (the twelfth within 0.035 — the recorder
purge boundary had moved between runs). The backfilled 07-13…08-13 series also
matches an independent computation exactly. Nothing was fabricated.

## What diverged

**1. The 14d and 28d windows were the same ~9-day window, twice.**
`run_full_analysis.py` fetched HA history from the recorder, which purges after
~10 days. Every multi-window table in 08-14…08-21 shipped with its 14d and 28d
columns byte-identical. A 51-day archive existed in the repo the whole time;
the pipeline never read it.

**2. The front (onset) section compared candidates on different rows.**
Models had data for ~190 of the window's 581 dry hours; `always_alert` and
`persistence` were scored on all 581. "Onsets caught 6/18" charged models for
13 onsets they never saw. On full-coverage data the committed front AUCs of
0.64–0.77 measure **0.48–0.62** — the last ~9 days were simply an easy stretch.

**3. "Fitted model front AUC 0.889" rested on 38 held-out rows.**
With full data the same walk-forward measures **0.704 on 327 rows**. 0.889 was
small-sample noise, not a result.

## What changed in response

- The pipeline now merges **archive + long-term statistics + recorder** before
  analysis, so a 28-day window is 28 days of data (`run_full_analysis.py`).
- The front table gained a **"dry hours seen"** column with a starvation flag.
- 2026-08-14, 08-15 and 08-21 reports were **regenerated** on full data.
- `load_ha_csv` accepts mixed timestamp formats; the `rainlib` package
  re-exports the front API.

## The model question (and a new model)

Scored on the project's actual goal — from a dry hour, does rain *begin*
within 3 h — the registry measured (full 51-day local window, 44 onsets):
every spread-led model 0.48–0.61 AUC, persistence 0.485 (chance, as designed).
The spread derivative itself is *anti-correlated* with onsets at dry hours
(AUC 0.42 over 40k reanalysis hours): a closing spread at a dry hour argues
against imminent rain, which is why models built on it cannot warn.

**Added `onset_gate`** — a frozen four-term logistic (pressure anomaly vs
30-day median, fall from the 24-h pressure ridge, RH, 3-hour temperature
trend; no spread terms) fitted once on 2021–2025 reanalysis, so all scores
below are out-of-sample:

| dataset | front-3h ROC AUC |
|---|:---:|
| reanalysis 2025-03→2026-08 (held out) | 0.706 |
| local sensors 2026-07→08 | **0.739** |
| best other registered model, same rows | 0.611 |
| walk-forward fitted logistic (`analysis/learned.py`) | 0.777 |

The surprising term: at a dry hour, *rising* 3-h temperature raises onset
odds (convective heating feeding afternoon showers) — second-strongest
coefficient after pressure.

Candidates measured and **not** adopted: drop-from-peak/wind/wdir-change as
extra learned features (+0.002–0.004 AUC — the existing feature set already
carries the information); a 2–3-term threshold rule (tops out at lift ≈1.9×,
precision ≈0.22 — the frozen logistic dominates it at equal simplicity).

## Ceiling and next step

The walk-forward logistic's 0.777 is today's honest ceiling with local
sensors; cloud cover (API-only) adds ≈+0.05 on multi-year data. The gap
onset_gate→0.777 is the price of freezing coefficients; it buys immunity to
51-day overfitting and a formula a Home Assistant template can express. As the
archive grows, refitting on *local* data (with the same walk-forward guard)
becomes the next step past 0.74.
