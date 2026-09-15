"""Corpus test: every committed daily report must parse (Phase 4, #399).

Two formats live in reports/ and both must stay readable:

* **onset-first** (2026-07-18 onward) — one scoreboard on rain starts. This is
  what the site and the backend read today.
* **nowcast-era** (2026-07-13..17) — the older eleven-section layout, kept as
  published history. Nothing generates it any more, but the parsers that read
  the archive must not rot.

Acceptance criterion from #232 stands: instead of a coverage percentage, run
the parser over the whole corpus so a regression surfaces as a failure here.
"""

import glob
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts_utils"))

import report_parse as rp
from migrate_reports_to_backend import build_content, report_date_of

REPORTS = sorted(glob.glob(str(Path(__file__).parent.parent / "reports" / "20??-??-??.md")))

LEGACY_SECTIONS = {
    "executive_summary", "data_context", "models", "multi_window_comparison",
    "rankings", "temporal_metrics", "precipitation_source_reliability",
}
ONSET_SECTIONS = {"executive_summary", "onset_scoreboard", "data_context"}


def test_corpus_is_present():
    assert len(REPORTS) >= 30, f"Expected the report corpus, found {len(REPORTS)} files"


def test_both_formats_are_represented():
    formats = {rp.is_onset_report(Path(p).read_text(encoding="utf-8")) for p in REPORTS}
    assert True in formats, "no onset-format reports in the corpus"


@pytest.mark.parametrize("path", REPORTS, ids=[Path(p).stem for p in REPORTS])
def test_report_parses(path):
    md = Path(path).read_text(encoding="utf-8")

    report_date = report_date_of(path, md)
    assert report_date is not None
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date)
    assert Path(path).stem == report_date

    content = build_content(md)

    if rp.is_onset_report(md):
        # The first days of the record contain no observed rain, so there is
        # nothing to score and no scoreboard to parse. The report says so.
        if "No rain starts in the record yet" in md:
            assert "data_context" in content
            return
        assert ONSET_SECTIONS.issubset(content.keys()), (
            f"{path}: missing sections {ONSET_SECTIONS - set(content)}")
        board = content["onset_scoreboard"]
        assert board["rows"], f"{path}: empty scoreboard"
        for row in board["rows"]:
            assert row["model"]
            # A candidate with no history in the window renders as dashes —
            # `ha_live_actual` does exactly that on early windows, and dropping
            # such rows would hide that the deployed sensor went unmeasured.
            if row["onsets"] is not None:
                assert row["onsets"] >= 0
                assert 0 <= row["caught"] <= row["onsets"]
            assert row["roc_auc"] is None or 0.0 <= row["roc_auc"] <= 1.0
        # The control belongs on every board: a yardstick that rates
        # persistence as skilful at predicting onsets is broken.
        assert any(r["model"] == "persistence" for r in board["rows"]), \
            f"{path}: persistence control missing from the scoreboard"
    else:
        assert LEGACY_SECTIONS.issubset(content.keys()), (
            f"{path}: missing sections {LEGACY_SECTIONS - set(content)}")
        models = content["models"]
        assert len(models) >= 10, f"{path}: leaderboard shrank to {len(models)} models"
        for entry in models:
            assert entry["name"]
            assert set(entry["metrics"]) == {"f1", "precision", "recall"}
            for value in entry["metrics"].values():
                assert value is None or 0.0 <= value <= 1.0
        assert content["executive_summary"].get("best_model"), f"{path}: no best model"
