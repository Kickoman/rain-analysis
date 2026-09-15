"""
report_parse.py — one parser for the generated daily-report HTML.
=================================================================

The publishing pipeline renders reports to HTML and then reads structured data
back out of that HTML with regexes. Three generators used to do that reading,
each with its own copy of the patterns, and the copies had diverged. This module
is the single implementation they now share.

Two rules matter here, and both exist because of specific published-wrong-data
incidents:

**Locate the leaderboard, never "search until something matches."** The previous
implementations iterated every ``<table>`` in the document and returned the first
one that yielded any match. When the leaderboard held no numeric cells they fell
through to the *Temporal Metrics* table — a different measurement entirely (F1
under a ±3h/±1h tolerance, at per-model tuned thresholds, three rows per model)
— and published those figures as plain F1/precision/recall. Here the table is
found by its heading, and if that table yields nothing the answer is "nothing".

**``N/A`` is a value, not a parse failure.** Since 2026-08-13 a model with no
scored samples renders ``N/A`` rather than ``0.000``. Patterns matching only
``[0-9.]+`` treat that as "no match", which is what triggered the fall-through
above and separately made ``ha_live_actual`` vanish from the site. Null cells
parse to ``None`` and travel through the pipeline as such.
"""

from __future__ import annotations

import re

__all__ = [
    "strip_tags",
    "extract_date",
    "extract_best_model",
    "extract_leaderboard",
    "find_leaderboard_table",
    "leaderboard_f1",
]


# Cells that mean "no value" rather than a number.
NULL_TOKENS = {"n/a", "na", "-", "--", "—", "–", ""}

# The leaderboard's own heading. Every daily report since 2026-07-13 has it.
_LEADERBOARD_HEADING = re.compile(
    r"<h2[^>]*>\s*Model Performance\b", re.IGNORECASE)

_TABLE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)

_NUMBER = r"[0-9]*\.?[0-9]+(?:[eE][+-]?\d+)?"
_CELL = rf"(?:{_NUMBER}|N/?A|—|–|-{{1,2}})"

# Anchored on <tr><td>: a model name must be a whole cell, never a substring of
# one. Without the anchor "combined" matches inside "pressure_combined</td>" and
# reports that row's score instead.
_ROW = re.compile(
    rf"<tr>\s*<td[^>]*>\s*([A-Za-z][\w_]*)\s*</td>\s*"
    rf"<td[^>]*>\s*({_CELL})\s*</td>\s*"
    rf"<td[^>]*>\s*({_CELL})\s*</td>\s*"
    rf"<td[^>]*>\s*({_CELL})\s*</td>",
    re.IGNORECASE,
)


def strip_tags(html: str) -> str:
    """Remove HTML tags so prose can be matched as plain text."""
    return re.sub(r"<[^>]+>", "", html)


def extract_date(text: str) -> str | None:
    """Report date from the ``Daily Model Analysis — YYYY-MM-DD`` title."""
    m = re.search(r"Daily Model Analysis[^—]*[—–-]\s*(\d{4}-\d{2}-\d{2})", text)
    return m.group(1) if m else None


def extract_best_model(text: str) -> str | None:
    """Model named on the ``Best overall (F-beta=N): <model> @ T%`` line."""
    m = re.search(r"Best overall[^:]*:\s*([\w_]+)", text)
    return m.group(1) if m else None


def _parse_cell(raw: str) -> float | None:
    """A metric cell as a float, or None when it reports no value."""
    token = raw.strip()
    if token.lower() in NULL_TOKENS:
        return None
    try:
        return float(token)
    except ValueError:
        return None


def find_leaderboard_table(html: str) -> tuple[str | None, str]:
    """Return ``(table_html, how_it_was_found)`` for the model leaderboard.

    ``how`` is ``"heading"`` when anchored on the ``Model Performance`` heading,
    ``"first-table"`` for older reports that predate it, or ``"missing"``.
    Callers that care about provenance can log it; the important property is
    that only one table is ever considered.
    """
    heading = _LEADERBOARD_HEADING.search(html)
    if heading:
        table = _TABLE.search(html, heading.end())
        if table:
            return table.group(0), "heading"
        return None, "missing"

    # Reports older than the leaderboard heading: the first table is the only
    # table. Deliberately not a fallback for *newer* reports — there, a missing
    # heading means the report is malformed, and guessing is how wrong numbers
    # got published before.
    table = _TABLE.search(html)
    if table:
        return table.group(0), "first-table"
    return None, "missing"


def extract_leaderboard(html: str) -> list[dict]:
    """Parse the leaderboard into ``[{model, f1, precision, recall}, ...]``.

    Metrics are ``float`` or ``None``; ``None`` means the report said ``N/A``,
    i.e. the model had no scored samples. Returns ``[]`` when the leaderboard
    cannot be located — never the contents of some other table.
    """
    table, _ = find_leaderboard_table(html)
    if table is None:
        return []

    rows = []
    seen = set()
    for m in _ROW.finditer(table):
        model = m.group(1)
        if model in seen:
            continue
        seen.add(model)
        rows.append({
            "model": model,
            "f1": _parse_cell(m.group(2)),
            "precision": _parse_cell(m.group(3)),
            "recall": _parse_cell(m.group(4)),
        })
    return rows


def leaderboard_f1(html: str, model_name: str) -> float | None:
    """F1 for one model from the leaderboard, or None if absent or ``N/A``."""
    for row in extract_leaderboard(html):
        if row["model"] == model_name:
            return row["f1"]
    return None


# ---------------------------------------------------------------------------
# Markdown-native extractors (Phase 4 migration, #399/#400)
#
# Same rules as the HTML side: sections are located by their headings, and
# ``N/A`` is a value (None), not a parse failure. These operate on the raw
# report markdown so the backend migration does not depend on the HTML
# rendering pipeline.
# ---------------------------------------------------------------------------

_MD_H2 = re.compile(r"^##\s+(.+?)\s*$", re.M)
_MD_H3 = re.compile(r"^###\s+(.+?)\s*$", re.M)
_MD_TABLE_ROW = re.compile(r"^\|(.+)\|\s*$", re.M)


def split_markdown_sections(text: str) -> list[tuple[str, str]]:
    """Split report markdown into ``(h2_title, body)`` pairs, in order."""
    matches = list(_MD_H2.finditer(text))
    sections = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((m.group(1), text[m.end():end].strip()))
    return sections


def markdown_section(text: str, title_pattern: str) -> str | None:
    """Body of the first ``##`` section whose title matches the regex."""
    pattern = re.compile(title_pattern)
    for title, body in split_markdown_sections(text):
        if pattern.search(title):
            return body
    return None


def parse_markdown_table(block: str) -> list[dict]:
    """First markdown table in ``block`` as header-keyed rows.

    Cell values stay raw strings (callers decide what is numeric);
    the ``|---|`` separator row is dropped. Returns ``[]`` without a table.
    """
    rows = [
        [cell.strip() for cell in m.group(1).split("|")]
        for m in _MD_TABLE_ROW.finditer(block)
    ]
    if len(rows) < 2:
        return []
    header = rows[0]
    out = []
    for row in rows[1:]:
        if all(re.fullmatch(r":?-{2,}:?", cell) for cell in row if cell):
            continue  # separator row
        if len(row) != len(header):
            continue
        out.append(dict(zip(header, row)))
    return out


def extract_leaderboard_md(text: str) -> list[dict]:
    """Markdown counterpart of :func:`extract_leaderboard`.

    Reads the ``Model Performance`` section's table into
    ``[{model, f1, precision, recall, status}, ...]`` with metric cells as
    float-or-None. Returns ``[]`` when the section or table is missing.
    """
    body = markdown_section(text, r"Model Performance")
    if body is None:
        return []
    rows = []
    seen = set()
    for raw in parse_markdown_table(body):
        model = raw.get("Model", "").strip()
        if not model or model in seen:
            continue
        seen.add(model)
        rows.append({
            "model": model,
            "f1": _parse_cell(raw.get("F1", "")),
            "precision": _parse_cell(raw.get("Precision", "")),
            "recall": _parse_cell(raw.get("Recall", "")),
            "status": raw.get("Status", "").strip() or None,
        })
    return rows


def markdown_subsections(body: str) -> list[tuple[str, str]]:
    """Split a section body into ``(h3_title, sub_body)`` pairs."""
    matches = list(_MD_H3.finditer(body))
    subs = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        subs.append((m.group(1), body[m.end():end].strip()))
    return subs


# ---------------------------------------------------------------------------
# Onset-first reports (2026-09-15 onward)
#
# The daily report no longer leads with a nowcast leaderboard, because nothing
# in the product asks whether it is raining right now. What it publishes is one
# scoreboard on rain *starts*, and these read it. The older extractors above
# still work on the archived reports that have a "Model Performance" table.
# ---------------------------------------------------------------------------

_ONSET_TITLE = re.compile(
    r"Rain Onset Report[^—–-]*[—–-]\s*(\d{4}-\d{2}-\d{2})")

_ONSET_HEADING = re.compile(r"<h2[^>]*>\s*Onset scoreboard\b", re.IGNORECASE)

_VERDICT_MARK = {"✅": "works", "◐": "ranks_only", "⚠️": "one_label_only",
                 "—": "chance", "…": "insufficient_evidence", "?": "unknown"}

# candidate | catches | if random | lift | alert h/wk | lead | AUC (CI) | cross | mark
_ONSET_ROW = re.compile(
    r"<tr>\s*<td[^>]*>\s*<code>([\w_]+)</code>[^<]*(?:<em>[^<]*</em>)?\s*</td>\s*"
    r"<td[^>]*>\s*(\d+)\s*/\s*(\d+)\s*</td>\s*"
    r"<td[^>]*>\s*([^<]*?)\s*</td>\s*"      # expected if random
    r"<td[^>]*>\s*([^<]*?)\s*</td>\s*"      # lift
    r"<td[^>]*>\s*([^<]*?)\s*</td>\s*"      # alert hours per week
    r"<td[^>]*>\s*([^<]*?)\s*</td>\s*"      # median lead
    r"<td[^>]*>\s*([^<]*?)\s*</td>\s*"      # AUC (CI)
    r"<td[^>]*>\s*([^<]*?)\s*</td>\s*"      # cross-label AUC
    r"<td[^>]*>\s*([^<]*?)\s*</td>",        # verdict mark
    re.IGNORECASE,
)

_AUC_WITH_CI = re.compile(rf"({_NUMBER})\s*\(({_NUMBER})[–-]({_NUMBER})\)")


def is_onset_report(text: str) -> bool:
    """True for the onset-first format, in markdown or rendered HTML."""
    return _ONSET_TITLE.search(text) is not None


def extract_onset_date(text: str) -> str | None:
    m = _ONSET_TITLE.search(text)
    return m.group(1) if m else None


def extract_onset_scoreboard(html: str) -> list[dict]:
    """Parse the onset scoreboard into one dict per candidate.

    Located by its heading for the same reason the leaderboard is: the report
    holds more than one table, and picking "the first one" is how Temporal
    Metrics once got published as F1.
    """
    heading = _ONSET_HEADING.search(html)
    if not heading:
        return []
    table = _TABLE.search(html, heading.end())
    if not table:
        return []

    rows = []
    for m in _ONSET_ROW.finditer(table.group(0)):
        auc, lo, hi = None, None, None
        ci = _AUC_WITH_CI.search(m.group(8))
        if ci:
            auc, lo, hi = (float(ci.group(1)), float(ci.group(2)), float(ci.group(3)))
        else:
            auc = _parse_cell(m.group(8))
        rows.append({
            "model": m.group(1),
            "caught": int(m.group(2)),
            "onsets": int(m.group(3)),
            "event_recall": int(m.group(2)) / int(m.group(3)) if int(m.group(3)) else None,
            "expected_if_random": _parse_cell(m.group(4)),
            "lift": _parse_cell(m.group(5)),
            "alert_hours_per_week": _parse_cell(m.group(6)),
            "median_lead_hours": _parse_cell(m.group(7)),
            "roc_auc": auc,
            "roc_auc_ci": [lo, hi] if lo is not None else None,
            "cross_label_auc": _parse_cell(m.group(9)),
            "verdict": _VERDICT_MARK.get(strip_tags(m.group(10)).strip(), None),
        })
    return rows


def extract_recommended(text: str) -> dict | None:
    """The verdict's recommendation: which candidate at which threshold."""
    m = re.search(r"Run\s+`?([\w_]+)`?\s+at\s+(\d+)%", strip_tags(text))
    if not m:
        return None
    return {"model": m.group(1), "threshold": float(m.group(2))}


def extract_onset_window(text: str) -> dict:
    """Window size and onset counts from the scoreboard's header line."""
    plain = strip_tags(text).replace("**", "")
    out = {}
    m = re.search(r"Window:\s*([0-9.]+)\s*days", plain)
    if m:
        out["window_days"] = float(m.group(1))
    m = re.search(r"onsets:\s*(\d+)\s*\(Open-Meteo\)\s*/\s*(\d+)", plain)
    if m:
        out["onsets"] = int(m.group(1))
        out["onsets_cross_label"] = int(m.group(2))
    return out


def extract_onset_scoreboard_md(text: str) -> list[dict]:
    """Markdown counterpart of :func:`extract_onset_scoreboard`.

    The backend migration reads the committed markdown directly rather than
    the rendered HTML, so the same table has to be readable both ways.
    """
    body = markdown_section(text, r"Onset scoreboard")
    if body is None:
        return []

    rows = []
    marks = {"✅": "works", "◐": "ranks_only", "⚠️": "one_label_only", "—": "chance",
             "…": "insufficient_evidence"}
    for raw in parse_markdown_table(body):
        name = raw.get("Candidate", "")
        m = re.search(r"`([\w_]+)`", name)
        if not m:
            continue
        caught = re.match(r"\s*(\d+)\s*/\s*(\d+)", raw.get("Catches", "") or "")
        auc_cell = raw.get("Front AUC (95% CI)", "") or ""
        ci = _AUC_WITH_CI.search(auc_cell)
        verdict_cell = (raw.get("", "") or "").strip()
        rows.append({
            "model": m.group(1),
            "caught": int(caught.group(1)) if caught else None,
            "onsets": int(caught.group(2)) if caught else None,
            "expected_if_random": _parse_cell(raw.get("If random", "")),
            "lift": _parse_cell(raw.get("Lift", "")),
            "alert_hours_per_week": _parse_cell(raw.get("Alert h/wk", "")),
            "median_lead_hours": _parse_cell(raw.get("Lead", "")),
            "roc_auc": float(ci.group(1)) if ci else _parse_cell(auc_cell),
            "roc_auc_ci": [float(ci.group(2)), float(ci.group(3))] if ci else None,
            "cross_label_auc": _parse_cell(raw.get("Meteostat AUC", "")),
            "verdict": marks.get(verdict_cell),
        })
    return rows
