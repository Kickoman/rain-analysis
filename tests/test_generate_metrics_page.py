"""Tests for the onset metrics page.

The page this file used to test plotted per-model F1 and parsed the
"Precipitation Source Reliability" table. Both are gone: the report no longer
scores the nowcast target, so there is no F1 series to plot and no such table
to read. What matters now is that the timeline is assembled only from reports
scored on rain starts, and that older reports are skipped rather than spliced
into it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts_utils"))

from generate_metrics_page import collect  # noqa: E402

ONSET_HTML = """
<h1>Rain Onset Report — 2026-09-14</h1>
<h2>Onset scoreboard</h2>
<p><strong>Window:</strong> 59.0 days · <strong>onsets:</strong> 29 (Open-Meteo) / 20 (Meteostat)</p>
<table>
<tr><td><code>pressure_primary</code></td><td>13/29</td><td>9.2</td><td>1.42</td>
<td>18</td><td>3.0</td><td>0.69 (0.64–0.75)</td><td>0.69</td><td>✅</td></tr>
<tr><td><code>ha_live_actual</code></td><td>11/29</td><td>9.7</td><td>1.13</td>
<td>20</td><td>2.0</td><td>0.50 (0.41–0.58)</td><td>0.48</td><td>—</td></tr>
</table>
"""

LEGACY_HTML = """
<h1>Daily Model Analysis — 2026-08-01</h1>
<h2>Model Performance (7-day window)</h2>
<table><tr><td>combined</td><td>0.548</td><td>0.451</td><td>0.697</td></tr></table>
"""


def test_collect_reads_onset_reports(tmp_path):
    history = tmp_path / "history"
    history.mkdir()
    (history / "2026-09-14.html").write_text(ONSET_HTML)

    dates, series, latest, skipped = collect(history)

    assert dates == ["2026-09-14"]
    assert skipped == []
    assert series["pressure_primary"]["auc"] == [0.69]
    assert series["pressure_primary"]["lift"] == [1.42]
    assert series["ha_live_actual"]["auc"] == [0.50]
    assert {r["model"] for r in latest} == {"pressure_primary", "ha_live_actual"}
    assert latest[0]["onsets"] == 29


def test_collect_skips_pre_onset_reports(tmp_path):
    """A nowcast-era report must not be spliced into the onset timeline."""
    history = tmp_path / "history"
    history.mkdir()
    (history / "2026-08-01.html").write_text(LEGACY_HTML)
    (history / "2026-09-14.html").write_text(ONSET_HTML)

    dates, _, _, skipped = collect(history)

    assert dates == ["2026-09-14"]
    assert [name for name, _ in skipped] == ["2026-08-01.html"]


def test_collect_leaves_gaps_for_absent_candidates(tmp_path):
    """A model missing from one report gets a gap, not a carried-forward value."""
    history = tmp_path / "history"
    history.mkdir()
    without = ONSET_HTML.replace(
        "<tr><td><code>ha_live_actual</code></td><td>11/29</td><td>9.7</td><td>1.13</td>\n"
        "<td>20</td><td>2.0</td><td>0.50 (0.41–0.58)</td><td>0.48</td><td>—</td></tr>", "")
    (history / "2026-09-13.html").write_text(without.replace("2026-09-14", "2026-09-13"))
    (history / "2026-09-14.html").write_text(ONSET_HTML)

    dates, series, _, _ = collect(history)

    assert dates == ["2026-09-13", "2026-09-14"]
    assert series["ha_live_actual"]["auc"] == [None, 0.50]
