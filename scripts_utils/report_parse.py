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
