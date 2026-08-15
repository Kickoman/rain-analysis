# Recomputed history — what the corrected record says

**Written 2026-08-15**, after regenerating every daily report from 2026-07-13 to
2026-08-13 with the fixed measurement harness (`scripts_utils/backfill_reports.py`),
plus one evaluation over the whole archived period, 2026-07-01 → 2026-08-14
(1,041 scored hours, ~245 rain hours;
`reports/full-period-2026-07-01-2026-08-13/analysis_report.json`).

The original reports for those dates were produced by the pre-2026-08-13 harness
and their numbers were artifacts (10-minute grid, unclipped window, row-based
fill limit, replica reading the wrong sensor — see `docs_site/CHANGELOG.md`).
Each regenerated report carries a provenance note. Yandex snapshots were not
reachable from the recompute environment; everything else came from committed
inputs (`data/archive/`), so the whole run is reproducible.

## Conclusions about the models

**1. Persistence beats every hand-written model, on both targets.**
Full period, nowcast: persistence ROC AUC **0.808**, best model
(`pressure_primary`) **0.638**. Warning target (rain within 3 h): persistence
0.712 / F1 0.612, best model 0.628 / F1 0.431. Nothing hand-tuned comes close
to "say what happened last hour".

**2. The only thing that beats persistence is the learned model.**
Walk-forward logistic regression, held-out rows only: nowcast AUC **0.751** vs
persistence 0.739 on the same rows; within-3h **0.766** vs 0.643. The gap on
the warning target — the one the product needs — is large (+0.12), and the
comparison is honest: every competing model was scored on the identical rows.

**3. The pressure family is one model wearing seven names.**
Full-period nowcast AUCs: `pressure_primary` 0.638, then 0.630–0.634 for
`combined`, `pressure_absolute`, `pressure_combined`, `pressure_lagged`,
`tuned`, `pressure_long_window`, `pressure_aware`. On 28-day windows their
means sit within 0.008 of each other. These differences are far inside window-
to-window noise (7-day AUC sd ≈ 0.14). Keep `pressure_primary` — best on the
full period on both targets, best 28-day mean, and best against the Meteostat
ground truth too (F1 0.459) — and retire the rest as duplicates.

**4. The production alert path is at the bottom of the table.**
`ha_live_replica`: full-period nowcast AUC 0.579, within-3h 0.551, mean 7-day
AUC 0.517. `trend_dominant` is at chance on the nowcast (0.504) and **below
chance on the warning target (0.435)** — consistent with the finding that the
spread derivative carries no signal (`plans/model-improvements.md`, finding 3).

**5. Seven-day windows cannot rank models — even with the harness fixed.**
Across the 32 recomputed days the 7-day "best model" changed 12 times, and
`trend_dominant` collected 14 of the 32 daily crowns purely by variance (its
sd-band spans chance). The same 32 days of 28-day windows produce a stable
order. Ranking policy should follow: the daily report may *display* 7-day
numbers, but any "best model" statement belongs to the 28-day window at
minimum, and decisions to the full archive.

## Conclusions about thresholds

**6. At min_precision 0.6, most models have no usable threshold at all.**
Over the full period the F-beta=2 recommendation is empty (no threshold reaches
precision 0.6) for every pressure-family model; only `ha_live_replica` clears
the floor, at threshold 65 with recall 0.126. The scores are not calibrated
probabilities (weights sum to >1, hysteresis holds values up), so the fixed 50%
cutoff compares nothing comparable. A calibrated probability — the logistic
model — is the clean fix; failing that, thresholds must be re-fit per model on
a trailing window.

**7. The alert rule's humidity threshold should come down to ≈70.**
`docs_site/ALERT_RULE.md` gates on local RH > 75, but the local humidity sensor
reads **−7.07 %RH** against Open-Meteo (report 2026-08-13, n=169). Sweeping the
rule on archived local sensors (652 usable hours, target rain-within-3h):

| anomaly | RH > | precision | recall |
|:---:|:---:|:---:|:---:|
| −3 | 75 | 0.789 | 0.188 |
| −3 | 70 | 0.767 | 0.206 |
| −3 | 68 | 0.755 | 0.250 |
| −2 | 68 | 0.510 | 0.319 |

Dropping RH 75→68 buys a third more recall at ~3 points of precision. Caveats:
the sample is small, and the pressure-anomaly baseline (30-day median) only
has full history from ~2026-08-11, so the rule should be re-swept after a
month of clean data. Recommendation: deploy with RH > 70 now, revisit in
September.

## Where to go next (ordered)

1. **Deploy the replacement alert** (`docs_site/ALERT_RULE.md`) with the
   humidity gate at 70, keeping anomaly < −3. `delay_on`/`delay_off` are
   YAML-only — the UI helper does not expose them.
2. **Collapse the pressure family to `pressure_primary`** in `MODELS` and the
   daily report. Seven near-identical rows hide the real comparisons.
3. **Promote the logistic model** along Stage 4 of
   `plans/model-improvements.md` — it is the only rank-capable predictor that
   beats persistence, and its calibrated output is what makes a threshold
   meaningful. Needs the backend to serve it (roadmap Phase 3).
4. **Change the report's ranking policy**: best-model statements from 28-day
   windows or longer; 7-day tables shown but flagged as unstable.
5. **Keep the archive growing** (`archive_ha_data.py` daily) — every ceiling
   here is 43 days of local history. Cloud cover (+0.061 AUC, the largest
   single missing feature) and a local rain sensor (ground truth; κ between
   OM and Meteostat is only ~0.5) are the two data acquisitions that matter.
