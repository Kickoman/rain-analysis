"""
Tests for check_site — the gate that refuses to publish a shrinking site.

The deploy regenerates everything and pushes with an unconditional `git add .`,
so a generator that quietly produced nothing looked exactly like a successful
run. This gate compares the tree about to be published against the one currently
live and fails on loss. Growth is always allowed; only loss is suspicious.
"""

import json
from pathlib import Path

import pytest

import check_site


def build_site(root: Path, cards: int = 3, dates=None, models=None) -> Path:
    """A minimally plausible generated site."""
    dates = dates if dates is not None else ["2026-08-11", "2026-08-12", "2026-08-13"]
    models = models if models is not None else ["combined", "tuned", "ha_live_actual"]

    (root / "current").mkdir(parents=True, exist_ok=True)
    (root / "history").mkdir(parents=True, exist_ok=True)
    (root / "metrics").mkdir(parents=True, exist_ok=True)

    filler = "<p>" + "x" * 1200 + "</p>"
    (root / "index.html").write_text(filler, encoding="utf-8")
    (root / "current/index.html").write_text(filler, encoding="utf-8")
    (root / "history/index.html").write_text(
        filler + '<div class="card">c</div>' * cards, encoding="utf-8")
    (root / "metrics/index.html").write_text(filler, encoding="utf-8")
    (root / "metrics/data.json").write_text(data_json(dates, models), encoding="utf-8")
    return root


def data_json(dates, models) -> str:
    """Shaped like the real file, which the size floor is calibrated against."""
    return json.dumps({
        "dates": dates,
        "models": {
            m: {metric: [None] * len(dates) for metric in ("f1", "precision", "recall")}
            for m in models
        },
        "best_per_day": [""] * len(dates),
        "source_data": {},
    }, indent=2)


# ---------------------------------------------------------------------------
# Completeness
# ---------------------------------------------------------------------------

def test_complete_site_passes(tmp_path):
    build_site(tmp_path)
    assert check_site.check_required_pages(tmp_path) == []


@pytest.mark.parametrize("missing", sorted(check_site.REQUIRED_PAGES))
def test_missing_page_is_reported(tmp_path, missing):
    build_site(tmp_path)
    (tmp_path / missing).unlink()

    problems = check_site.check_required_pages(tmp_path)
    assert any(missing in p and "missing" in p for p in problems)


def test_stub_page_is_reported(tmp_path):
    """A page that collapsed to an empty shell still exists on disk."""
    build_site(tmp_path)
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")

    problems = check_site.check_required_pages(tmp_path)
    assert any("index.html" in p and "bytes" in p for p in problems)


# ---------------------------------------------------------------------------
# History cards
# ---------------------------------------------------------------------------

def test_history_growth_is_allowed(tmp_path):
    build_site(tmp_path, cards=5)
    baseline = '<div class="card">c</div>' * 3
    assert check_site.check_history(tmp_path, baseline) == []


def test_history_loss_is_blocked(tmp_path):
    build_site(tmp_path, cards=2)
    baseline = '<div class="card">c</div>' * 30

    problems = check_site.check_history(tmp_path, baseline)
    assert problems and "reports were lost" in problems[0]


def test_empty_history_is_blocked_even_without_a_baseline(tmp_path):
    build_site(tmp_path, cards=0)
    assert check_site.check_history(tmp_path, None) == ["history/index.html: no report cards"]


# ---------------------------------------------------------------------------
# Metrics series
# ---------------------------------------------------------------------------

def test_dropped_dates_are_blocked(tmp_path):
    build_site(tmp_path, dates=["2026-08-11"])
    baseline = data_json(["2026-08-11", "2026-08-12", "2026-08-13"], ["combined"])

    problems = check_site.check_metrics(tmp_path, baseline)
    assert any("date(s) dropped" in p for p in problems)


def test_dropped_model_is_blocked(tmp_path):
    """The ha_live_actual failure: its rows went N/A and it left the site."""
    build_site(tmp_path, models=["combined", "tuned"])
    baseline = data_json(["2026-08-11", "2026-08-12", "2026-08-13"],
                         ["combined", "tuned", "ha_live_actual"])

    problems = check_site.check_metrics(tmp_path, baseline)
    assert any("ha_live_actual" in p for p in problems)


def test_model_present_with_null_metrics_is_fine(tmp_path):
    """No-data is an honest state; only disappearing is a failure."""
    build_site(tmp_path)
    baseline = data_json(["2026-08-11", "2026-08-12", "2026-08-13"],
                         ["combined", "tuned", "ha_live_actual"])
    assert check_site.check_metrics(tmp_path, baseline) == []


def test_new_model_and_new_date_are_fine(tmp_path):
    build_site(tmp_path,
               dates=["2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14"],
               models=["combined", "tuned", "ha_live_actual", "brand_new"])
    baseline = data_json(["2026-08-11", "2026-08-12", "2026-08-13"],
                         ["combined", "tuned", "ha_live_actual"])
    assert check_site.check_metrics(tmp_path, baseline) == []


def test_malformed_json_is_blocked(tmp_path):
    build_site(tmp_path)
    (tmp_path / "metrics/data.json").write_text("{not json", encoding="utf-8")

    problems = check_site.check_metrics(tmp_path, None)
    assert any("not valid JSON" in p for p in problems)


def test_empty_series_is_blocked(tmp_path):
    build_site(tmp_path, dates=[], models=[])
    problems = check_site.check_metrics(tmp_path, None)
    assert "metrics/data.json: no dates" in problems
    assert "metrics/data.json: no models" in problems


def test_unreadable_baseline_does_not_block_a_valid_site(tmp_path):
    """A corrupt published copy is not a reason to refuse a good new one."""
    build_site(tmp_path)
    assert check_site.check_metrics(tmp_path, "{corrupt") == []


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

def test_main_passes_on_a_good_site(tmp_path, monkeypatch, capsys):
    build_site(tmp_path)
    monkeypatch.setattr("sys.argv", ["check_site.py", "--root", str(tmp_path), "--no-baseline"])
    assert check_site.main() == 0
    assert "checks passed" in capsys.readouterr().out


def test_main_fails_on_an_incomplete_site(tmp_path, monkeypatch):
    build_site(tmp_path)
    (tmp_path / "metrics/data.json").unlink()
    monkeypatch.setattr("sys.argv", ["check_site.py", "--root", str(tmp_path), "--no-baseline"])
    assert check_site.main() == 1
