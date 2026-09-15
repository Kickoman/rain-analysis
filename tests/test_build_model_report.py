"""Tests for scripts_utils/build_model_report.py — the one-page model review.

The failure this guards against is a silent one: a model missing from a window
must leave a gap in the chart, never a zero, because a zero on this scale reads
as "predicts the opposite of reality" rather than "was not running yet".
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts_utils"))

import build_model_report as bmr

REPO = Path(__file__).parent.parent
REPORTS = REPO / "reports/daily"


def _report(scores, onsets=12, base=0.07):
    return {"scoring": {"front_target": {"scores": scores, "n_onsets": onsets,
                                         "base_rate": base}}}


def test_missing_model_leaves_a_gap_not_a_zero():
    reports = {
        "2026-08-01": _report({"a": {"roc_auc": 0.6}}),
        "2026-08-02": _report({"a": {"roc_auc": 0.7}, "b": {"roc_auc": 0.4}}),
    }
    series = bmr.front_series(reports)
    assert series["b"] == {"2026-08-02": 0.4}
    assert "2026-08-01" not in series["b"]


def test_null_and_nan_scores_are_dropped():
    reports = {"2026-08-01": _report({
        "a": {"roc_auc": None},
        "b": {"roc_auc": float("nan")},
        "c": {"roc_auc": 0.55},
        "d": None,
    })}
    assert bmr.front_series(reports) == {"c": {"2026-08-01": 0.55}}


def test_path_breaks_on_gaps():
    d = bmr._path([(0, 0), None, (10, 10), (20, 20)])
    assert d.count("M") == 2 and d.count("L") == 1


def test_ranking_reports_spread_and_skips_sparse_models():
    series = {"full": {"d1": 0.6, "d2": 0.8}, "sparse": {"d1": 0.9}}
    rows = bmr.ranking(series, ["d1", "d2", "d3", "d4"])
    assert [r["name"] for r in rows] == ["full"]
    row = rows[0]
    assert row["mean"] == pytest.approx(0.7)
    assert (row["lo"], row["hi"], row["n"]) == (0.6, 0.8, 2)


def test_alert_cost_skips_candidates_without_events():
    report = _report({
        "with": {"roc_auc": 0.7, "events": {"threshold": 60.0, "episodes_per_day": 1.2,
                                            "precision": 0.2, "onsets_caught": 5}},
        "without": {"roc_auc": 0.6, "events": None},
    })
    rows = bmr.alert_cost(report)
    assert [r["name"] for r in rows] == ["with"]
    assert rows[0]["onsets"] == 12


@pytest.mark.skipif(not REPORTS.exists(), reason="report corpus not available")
def test_renders_a_complete_page_from_the_real_corpus():
    reports = bmr.load_reports(REPORTS)
    assert len(reports) >= 40, "corpus shrank unexpectedly"

    grid = [{"t": f"2026-09-0{1 + i // 24} {i % 24:02d}:00", "truth": float(i % 17 == 0),
             "precip": 0.2 if i % 17 == 0 else 0.0, "best": 40.0 + i % 30,
             "live": 20.0 + i % 15}
            for i in range(96)]

    page = bmr.render(reports, grid)

    assert page.startswith("<!DOCTYPE html>") and page.rstrip().endswith("</html>")
    for heading in ("Что здесь считается успехом", "Как менялись результаты",
                    "Кто сколько набрал", "Сколько стоит одна тревога",
                    "Как это выглядит по часам", "Линейка сама кривая",
                    "Модели по-человечески", "Чему на этой странице верить нельзя"):
        assert heading in page, f"missing section: {heading}"

    assert page.count("<svg") == 6
    # Every colour must resolve from the light token block too, or the page
    # renders one theme's ink on the other theme's ground.
    css = page.split("<style>")[1].split("</style>")[0]
    light = css.split(":root {")[1].split("\n}")[0]
    used = {name for name in bmr.re.findall(r"var\(--([\w-]+)\)", page)}
    declared = {name for name in bmr.re.findall(r"--([\w-]+):", light)}
    assert not used - declared, f"tokens missing from the light palette: {used - declared}"


@pytest.mark.skipif(not REPORTS.exists(), reason="report corpus not available")
def test_every_window_has_a_sample_size_next_to_its_score():
    reports = bmr.load_reports(REPORTS)
    ctx = bmr.onset_context(reports)
    assert set(ctx) == set(reports)
    assert all(isinstance(onsets, int) and 0 <= base <= 1
               for onsets, base in ctx.values())
