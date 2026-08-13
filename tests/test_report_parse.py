"""
Tests for report_parse — the single parser for generated report HTML.

Two published-wrong-data incidents motivate most of these:

1. Parsers iterated every ``<table>`` and returned the first that yielded any
   match. An all-`N/A` leaderboard therefore fell through to *Temporal Metrics*
   — F1 under a ±3h/±1h tolerance at tuned thresholds, three rows per model —
   and those numbers were published as plain F1. Measured on the real
   2026-08-13 report: 30 rows returned where 0 were expected, with `combined`
   at 0.553 instead of its true 0.273.
2. The landing page matched a model name without a `<td>` anchor, so
   ``combined`` matched inside ``pressure_combined</td>``.
"""

from pathlib import Path

import pytest

from report_parse import (
    extract_best_model,
    extract_date,
    extract_leaderboard,
    find_leaderboard_table,
    leaderboard_f1,
    strip_tags,
)

REPO = Path(__file__).resolve().parent.parent


def report(leaderboard_rows: str, temporal_rows: str = "") -> str:
    """A document shaped like a real daily report."""
    temporal = f"""
    <h2>Temporal Metrics (lead=3h, lag=1h)</h2>
    <table>{temporal_rows}</table>
    """ if temporal_rows else ""
    return f"""
    <h1>Daily Model Analysis — 2026-08-13</h1>
    <p>Best overall (F-beta=2): tuned @ 55%</p>
    <h2>Model Performance (7-day window)</h2>
    <table>{leaderboard_rows}</table>
    {temporal}
    """


def row(model, f1="0.273", prec="0.375", rec="0.214"):
    return f"<tr><td>{model}</td><td>{f1}</td><td>{prec}</td><td>{rec}</td></tr>"


# ---------------------------------------------------------------------------
# Locating the table
# ---------------------------------------------------------------------------

def test_leaderboard_located_by_heading():
    html = report(row("combined"), row("combined", "0.553"))
    table, how = find_leaderboard_table(html)
    assert how == "heading"
    assert "0.273" in table and "0.553" not in table


def test_older_reports_without_the_heading_use_the_first_table():
    html = "<h2>Overall Leaderboard</h2><table>" + row("ha_live", "0.923") + "</table>"
    rows = extract_leaderboard(html)
    assert find_leaderboard_table(html)[1] == "first-table"
    assert rows[0]["f1"] == 0.923


def test_missing_table_yields_nothing():
    assert extract_leaderboard("<h2>Model Performance</h2><p>nothing here</p>") == []
    assert find_leaderboard_table("<p>no tables at all</p>") == (None, "missing")


# ---------------------------------------------------------------------------
# The fall-through regression
# ---------------------------------------------------------------------------

def test_all_na_leaderboard_never_returns_temporal_numbers():
    html = report(
        row("combined", "N/A", "N/A", "N/A") + row("tuned", "N/A", "N/A", "N/A"),
        row("combined", "0.553", "0.513", "0.600") + row("tuned", "0.527", "0.514", "0.540"),
    )
    rows = extract_leaderboard(html)

    assert [r["model"] for r in rows] == ["combined", "tuned"]
    assert all(r["f1"] is None for r in rows)
    assert not any(r["f1"] == 0.553 for r in rows)


def test_single_na_row_does_not_borrow_from_a_later_table():
    html = report(
        row("ha_live_actual", "N/A", "N/A", "N/A") + row("combined"),
        row("ha_live_actual", "0.500", "1.000", "0.333"),
    )
    assert leaderboard_f1(html, "ha_live_actual") is None
    assert leaderboard_f1(html, "combined") == 0.273


@pytest.mark.parametrize("token", ["N/A", "n/a", "NA", "—", "-", "--"])
def test_null_tokens_parse_to_none(token):
    rows = extract_leaderboard(report(row("m", token, token, token)))
    assert rows[0]["f1"] is None


# ---------------------------------------------------------------------------
# The substring regression
# ---------------------------------------------------------------------------

def test_model_name_matches_a_whole_cell_only():
    html = report(row("pressure_combined", "0.111") + row("combined", "0.999"))
    assert leaderboard_f1(html, "combined") == 0.999
    assert leaderboard_f1(html, "pressure_combined") == 0.111


def test_order_does_not_matter():
    html = report(row("combined", "0.999") + row("pressure_combined", "0.111"))
    assert leaderboard_f1(html, "combined") == 0.999


# ---------------------------------------------------------------------------
# Row parsing details
# ---------------------------------------------------------------------------

def test_header_row_is_not_a_model():
    html = report("<tr><th>Model</th><th>F1</th><th>Precision</th><th>Recall</th></tr>" + row("tuned"))
    assert [r["model"] for r in extract_leaderboard(html)] == ["tuned"]


def test_duplicate_rows_keep_the_first():
    html = report(row("tuned", "0.273") + row("tuned", "0.999"))
    rows = extract_leaderboard(html)
    assert len(rows) == 1 and rows[0]["f1"] == 0.273


def test_extra_status_column_is_ignored():
    html = report("<tr><td>tuned</td><td>0.273</td><td>0.375</td><td>0.214</td><td>✅</td></tr>")
    assert extract_leaderboard(html)[0]["precision"] == 0.375


def test_scientific_notation_and_bare_decimals():
    html = report(row("a", "1.23e-02", ".5", "0"))
    r = extract_leaderboard(html)[0]
    assert r["f1"] == pytest.approx(0.0123)
    assert r["precision"] == 0.5
    assert r["recall"] == 0.0


def test_whitespace_and_attributes_tolerated():
    html = report('<tr>\n<td class="x"> tuned </td>\n<td> 0.273 </td>\n<td>0.375</td>\n<td>0.214</td>\n</tr>')
    assert extract_leaderboard(html)[0]["model"] == "tuned"


# ---------------------------------------------------------------------------
# Prose helpers
# ---------------------------------------------------------------------------

def test_strip_tags():
    assert strip_tags("<p>Best overall: <b>tuned</b></p>").strip() == "Best overall: tuned"


def test_extract_date_and_best_model():
    text = strip_tags(report(row("tuned")))
    assert extract_date(text) == "2026-08-13"
    assert extract_best_model(text) == "tuned"


def test_extract_date_absent():
    assert extract_date("no title here") is None
    assert extract_best_model("no best model line") is None


# ---------------------------------------------------------------------------
# Against the real report
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not (REPO / "reports" / "2026-08-13.md").exists(), reason="report absent")
def test_real_report_keeps_the_no_data_model():
    """`ha_live_actual` reports N/A because sensor.rain_probability has no
    long-term statistics. It must survive parsing rather than disappear."""
    from md_to_html import markdown_to_html

    md = (REPO / "reports" / "2026-08-13.md").read_text()
    rows = extract_leaderboard(markdown_to_html(md, "2026-08-13"))

    by_name = {r["model"]: r for r in rows}
    assert "ha_live_actual" in by_name
    assert by_name["ha_live_actual"]["f1"] is None
    assert by_name["combined"]["f1"] == pytest.approx(0.273)
    assert len(rows) == 11
