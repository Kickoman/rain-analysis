"""Builds the whole site from real reports and checks what the design promises.

The generators are tested one at a time elsewhere. What no single-module test
can see is the page a reader actually gets: whether an emoji survived into the
markup, whether the stylesheet is reachable from the depth the page sits at,
whether a documentation card points at a page that exists. So this renders a
small but real site — two committed reports, every document, all four
generators — into a tmp directory and asserts against the result.

It is slower than the rest of the suite by a wide margin, and worth it: every
bug this would have caught was a bug that published cleanly.
"""

import glob
import os
import re
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
SCRIPTS = REPO / "scripts_utils"

# Anything in these ranges is a pictograph. Spelled as code points rather than
# escapes, because the dashes, ellipsis, middle dot, >= and degree sign the
# reports rely on sit just outside them and the boundaries are the whole point.
EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),   # pictographs, transport, symbols, extended-A
    (0x2190, 0x21FF),     # arrows
    (0x2300, 0x23FF),     # miscellaneous technical
    (0x2460, 0x27BF),     # enclosed alphanumerics, misc symbols, dingbats
    (0x2B00, 0x2BFF),     # supplemental arrows and stars
    (0x2139, 0x2139),     # the information glyph, alone below the blocks above
    (0xFE0F, 0xFE0F),     # variation selector 16 — the emoji presentation mark
)
EMOJI = re.compile("[" + "".join(f"{chr(lo)}-{chr(hi)}" for lo, hi in EMOJI_RANGES) + "]")

REPORTS = sorted(glob.glob(str(REPO / "reports" / "20??-??-??.md")))


def _run(script: str, *args: str) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"{script} failed:\n{result.stdout}\n{result.stderr}"


@pytest.fixture(scope="module")
def site(tmp_path_factory) -> Path:
    """A real site: two reports, every document, all four generators."""
    root = tmp_path_factory.mktemp("site")
    (root / "history").mkdir()
    (root / "current").mkdir()
    (root / "docs").mkdir()

    for path in REPORTS[-2:]:
        stem = Path(path).stem
        _run("md_to_html.py", path, str(root / "history" / f"{stem}.html"))
    _run("md_to_html.py", REPORTS[-1], str(root / "current" / "index.html"))

    for doc in sorted((REPO / "docs_site").glob("*.md")):
        _run("convert_docs_to_html.py", str(doc), str(root / "docs" / f"{doc.stem}.html"))

    # The generators write relative to the working directory, and one of them
    # ends in sys.exit(), so each runs inside its own try rather than taking
    # the rest of the build down with it.
    cwd = Path.cwd()
    try:
        os.chdir(root)
        for script in ("generate_history_index.py", "generate_landing_page.py",
                       "generate_metrics_page.py", "generate_404.py"):
            sys.argv = [script]
            try:
                runpy.run_path(str(SCRIPTS / script), run_name="__main__")
            except SystemExit as exc:
                assert not exc.code, f"{script} exited {exc.code}"
    finally:
        os.chdir(cwd)
    return root


def _pages(site: Path) -> list[Path]:
    return sorted(site.rglob("*.html"))


# ---------------------------------------------------------------------------
# The build itself
# ---------------------------------------------------------------------------

def test_every_expected_page_exists(site):
    for rel in ("index.html", "404.html", "current/index.html",
                "history/index.html", "metrics/index.html", "metrics/data.json",
                "docs/GLOSSARY.html"):
        assert (site / rel).exists(), f"{rel} was not generated"


def test_the_pages_are_not_stubs(site):
    for page in _pages(site):
        assert page.stat().st_size > 1000, f"{page.name} is {page.stat().st_size} bytes"


# ---------------------------------------------------------------------------
# No emoji anywhere
# ---------------------------------------------------------------------------

def test_no_emoji_survives_into_the_markup(site):
    """The design's one absolute rule: status is ASCII, never a pictograph."""
    offenders = []
    for page in _pages(site):
        for match in EMOJI.finditer(page.read_text(encoding="utf-8")):
            start = max(0, match.start() - 40)
            offenders.append(f"{page.relative_to(site)}: …{match.string[start:match.end() + 40]}…")
    assert not offenders, "emoji in generated HTML:\n" + "\n".join(offenders[:20])


def test_the_ascii_marks_did_arrive(site):
    """The counterpart: proof the pass ran rather than the pages being empty."""
    assert "[ok]" in (site / "index.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The shell, on every page
# ---------------------------------------------------------------------------

def test_every_page_reaches_its_stylesheet(site):
    for page in _pages(site):
        html = page.read_text(encoding="utf-8")
        match = re.search(r'<link rel="stylesheet" href="([^"]+)">', html)
        assert match, f"{page.relative_to(site)} has no stylesheet"
        href = match.group(1)
        if href.startswith("/"):
            continue                       # 404.html: absolute by necessity
        assert (page.parent / href).resolve().name == "style.css"
        assert (page.parent / href).resolve().parent.name == "assets"


def test_every_page_carries_the_theme_snippet(site):
    for page in _pages(site):
        assert "ra-theme" in page.read_text(encoding="utf-8"), page.relative_to(site)


def test_each_page_marks_its_own_nav_item(site):
    """The drift this replaced: history highlighted "Latest Report"."""
    expected = {
        "index.html": "home",
        "current/index.html": "latest report",
        "history/index.html": "history",
        "metrics/index.html": "metrics timeline",
        "docs/GLOSSARY.html": "glossary",
    }
    for rel, label in expected.items():
        html = (site / rel).read_text(encoding="utf-8")
        active = re.findall(r'<a href="[^"]*"\s+class="active">([^<]+)</a>', html)
        assert active == [label], f"{rel} marks {active}, expected [{label!r}]"


def test_a_report_page_marks_nothing_but_history(site):
    html = (site / "history" / f"{Path(REPORTS[-1]).stem}.html").read_text(encoding="utf-8")
    assert html.count('class="active"') == 1
    assert ">history</a>" in html


# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------

def test_landing_leads_with_the_terminal_panel(site):
    html = (site / "index.html").read_text(encoding="utf-8")
    panel = re.search(r"<pre>\$ rain-analysis status\n(.*?)</pre>", html, re.S)
    assert panel, "the status block is missing"
    body = panel.group(1)
    assert "report " in body and "recommended " in body and "deployed sensor " in body
    # One column: every value begins at the same offset, whatever its label.
    # The run of spaces inside a value ("59 days   onsets 29") is not the first
    # one on the line, so searching for the first is enough.
    starts = {re.search(r"\s{2,}", line).end() for line in body.splitlines()}
    assert len(starts) == 1, f"the panel's columns do not line up: {starts}"


def test_landing_widget_wiring_survives(site):
    html = (site / "index.html").read_text(encoding="utf-8")
    assert '<div id="live-rain-widget"></div>' in html
    assert '<script src="assets/live-widget.js" defer></script>' in html


def test_landing_tables_can_scroll(site):
    html = (site / "index.html").read_text(encoding="utf-8")
    assert html.count('<div class="table-wrap">') == html.count("<table>")


def test_documentation_cards_all_resolve(site):
    """A card built from a file that exists cannot 404. Prove it stays that way."""
    html = (site / "index.html").read_text(encoding="utf-8")
    section = html[html.index('<section class="documentation">'):]
    targets = re.findall(r'<a href="(docs/[^"]+)">', section)
    assert targets, "no documentation cards were generated"
    for target in targets:
        assert (site / target).exists(), f"dead documentation link: {target}"


def test_landing_offers_the_whole_docs_set(site):
    html = (site / "index.html").read_text(encoding="utf-8")
    generated = {p.stem for p in (site / "docs").glob("*.html")}
    linked = {Path(t).stem for t in re.findall(r'<a href="(docs/[^"]+)">', html)}
    assert generated == linked, f"not offered: {sorted(generated - linked)}"


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def test_metrics_page_carries_data_not_code(site):
    html = (site / "metrics" / "index.html").read_text(encoding="utf-8")
    assert '<script id="chart-data" type="application/json">' in html
    assert "Plotly.newPlot" not in html, "chart code belongs in assets/metrics-charts.js"
    assert 'src="../assets/metrics-charts.js"' in html


def test_chart_data_is_valid_json_with_every_chart(site):
    import json
    html = (site / "metrics" / "index.html").read_text(encoding="utf-8")
    payload = re.search(r'<script id="chart-data"[^>]*>(.*?)</script>', html, re.S).group(1)
    spec = json.loads(payload)
    assert [c["target"] for c in spec["charts"]] == ["auc-chart", "lift-chart", "cost-chart"]
    for chart in spec["charts"]:
        assert chart["traces"], f"{chart['target']} has no series"
        assert all(t["x"] for t in chart["traces"])


# ---------------------------------------------------------------------------
# History and 404
# ---------------------------------------------------------------------------

def test_history_lists_every_rendered_report(site):
    html = (site / "history" / "index.html").read_text(encoding="utf-8")
    reports = [p for p in (site / "history").glob("*.html") if p.name != "index.html"]
    assert html.count('<div class="card">') == len(reports)


def test_404_links_absolutely(site):
    """It is served from whatever depth the reader was browsing at."""
    html = (site / "404.html").read_text(encoding="utf-8")
    for href in re.findall(r'(?:href|src)="([^"]+)"', html):
        assert href.startswith(("/rain-analysis/", "http", "data:", "#")), href
