"""Corpus test: every committed daily report must parse (Phase 4, #399).

Acceptance criterion from #232: instead of a meaningless coverage
percentage, the parser is run over the full reports/20*.md corpus and
regressions surface as failures here.
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

EXPECTED_SECTIONS = {
    "executive_summary",
    "data_context",
    "models",
    "multi_window_comparison",
    "rankings",
    "temporal_metrics",
    "precipitation_source_reliability",
}


def test_corpus_is_present():
    assert len(REPORTS) >= 30, f"Expected the report corpus, found {len(REPORTS)} files"


@pytest.mark.parametrize("path", REPORTS, ids=[Path(p).stem for p in REPORTS])
def test_report_parses(path):
    md = open(path, encoding="utf-8").read()

    report_date = report_date_of(path, md)
    assert report_date is not None
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date)
    assert Path(path).stem == report_date

    content = build_content(md)

    # Every current-harness report carries the full section set; a report
    # parsing to fewer sections means a parser (or format) regression.
    assert EXPECTED_SECTIONS.issubset(content.keys()), (
        f"{path}: missing sections {EXPECTED_SECTIONS - set(content)}"
    )

    models = content["models"]
    assert len(models) >= 10, f"{path}: leaderboard shrank to {len(models)} models"
    for entry in models:
        assert entry["name"]
        assert set(entry["metrics"]) == {"f1", "precision", "recall"}
        for value in entry["metrics"].values():
            # N/A parses to None; numbers must be sane
            assert value is None or 0.0 <= value <= 1.0

    assert content["executive_summary"].get("best_model"), f"{path}: no best model"
