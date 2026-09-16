"""The round trip that guards the whole site: markdown -> HTML -> parsed back.

Three generators do not read the reports. They re-parse the HTML that
``md_to_html`` produced moments earlier, with regexes anchored on a bare
``<tr>`` and a first cell of exactly ``<td><code>name</code></td>``. So a
change to the report shell, to the table pass, to the glyphs or to the heading
ids can empty the landing hero, every history card and the entire metrics
timeline at once — and the build stays green, because nothing else looks at
those numbers.

This renders every committed report through the real converter and checks that
what comes back out of the HTML matches what the markdown itself says. It is
deliberately the dullest test in the suite: its value is that it fails loudly
the moment the rendered markup drifts away from what ``report_parse`` expects.
"""

import glob
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "scripts_utils"))

import report_parse as rp  # noqa: E402
from md_to_html import markdown_to_html  # noqa: E402

REPORTS = sorted(glob.glob(str(REPO / "reports" / "20??-??-??.md")))

# Fields that must survive rendering untouched. `verdict` is the one that is
# spelled differently either side of the glyph pass, so it is compared through
# the decoded enum rather than the raw mark.
COMPARED = ("model", "caught", "onsets", "lift", "roc_auc", "verdict")


def test_corpus_is_present():
    assert len(REPORTS) >= 30, f"expected the report corpus, found {len(REPORTS)}"


@pytest.mark.parametrize("path", REPORTS, ids=[Path(p).stem for p in REPORTS])
def test_rendered_report_parses_like_its_markdown(path):
    md = Path(path).read_text(encoding="utf-8")
    html = markdown_to_html(md, title=Path(path).stem)

    assert rp.is_onset_report(html) == rp.is_onset_report(md), (
        f"{path}: rendering changed whether this reads as an onset report"
    )
    if not rp.is_onset_report(md):
        pytest.skip("pre-onset report: covered by test_report_parse_corpus")

    assert rp.extract_onset_date(html) == rp.extract_onset_date(md)
    assert rp.extract_onset_window(html) == rp.extract_onset_window(md)
    assert rp.extract_recommended(html) == rp.extract_recommended(md)

    from_html = rp.extract_onset_scoreboard(html)
    from_md = rp.extract_onset_scoreboard_md(md)

    if not from_md:
        # The first days of the record hold no rain, so there is no scoreboard
        # in either form. Agreeing on "nothing" is still agreement.
        assert not from_html, f"{path}: HTML grew a scoreboard the markdown has not"
        return

    assert len(from_html) == len(from_md), (
        f"{path}: {len(from_md)} rows in markdown, {len(from_html)} parsed back "
        "from the rendered HTML — the row regex no longer matches what is emitted"
    )
    for html_row, md_row in zip(from_html, from_md):
        for field in COMPARED:
            assert html_row[field] == md_row[field], (
                f"{path}: {field} differs for {md_row['model']} — "
                f"{html_row[field]!r} from HTML, {md_row[field]!r} from markdown"
            )


def test_a_report_still_yields_a_full_scoreboard():
    """One concrete anchor, so a corpus-wide regression cannot read as 'all empty, all equal'."""
    latest = Path(REPORTS[-1]).read_text(encoding="utf-8")
    rows = rp.extract_onset_scoreboard(markdown_to_html(latest, title="latest"))
    assert len(rows) == 15, f"expected 15 candidates in the latest report, got {len(rows)}"
    assert any(r["verdict"] == "works" for r in rows)
