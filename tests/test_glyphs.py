"""ASCII glyphs in, emoji out — and nothing else touched.

The risk here is not that a glyph is missed; it is that the pass reaches too
far. ``to_ascii`` runs over whole markdown documents, including fenced code
and the aligned terminal status block, and over cells that ``report_parse``
reads numbers out of. Most of these tests are about what must survive.
"""

import pytest

from glyphs import to_ascii


# ---------------------------------------------------------------------------
# What changes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source,expected", [
    ("✅", "[ok]"),
    ("❌", "[x]"),
    ("⚠️", "[!]"),
    ("⚠", "[!]"),
    ("⛔", "[x]"),
    ("◐", "[~]"),
    ("🔄", "[~]"),
    ("⚪", "[ ]"),
    ("→", "->"),
    ("←", "<-"),
])
def test_status_glyphs_become_ascii(source, expected):
    assert to_ascii(source) == expected


@pytest.mark.parametrize("source,expected", [
    ("📈 improving", "IMPROVING"),
    ("📉 degrading", "DEGRADING"),
    ("➡️ stable", "STABLE"),
    ("⚪ no data", "[ ] no data"),
])
def test_trend_phrases_win_over_their_own_glyphs(source, expected):
    """Longest-first, or the cell reads "IMPROVING improving"."""
    assert to_ascii(source) == expected


def test_decorative_glyphs_take_their_trailing_space():
    assert to_ascii("🌧️ Will it rain?") == "Will it rain?"
    assert to_ascii("📊 Results") == "Results"


def test_a_decorative_glyph_with_nothing_after_it_still_goes():
    assert to_ascii("Results 📊") == "Results "


# ---------------------------------------------------------------------------
# What must not change
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "0.64–0.75",        # the en dash report_parse reads confidence intervals across
    "—",                # the null token
    "…",                # "insufficient evidence"
    "12 · 15",
    "≥ 0.5",
    "1.42×",
    "18.5 °C",
])
def test_typography_and_data_survive(text):
    assert to_ascii(text) == text


def test_alignment_is_never_collapsed():
    """The terminal panel and every fenced code block depend on this."""
    block = "report            2026-09-14\nrecord            59 days\n    indented"
    assert to_ascii(block) == block


def test_replacement_is_idempotent():
    once = to_ascii("✅ works → 📈 improving")
    assert to_ascii(once) == once


def test_empty_and_plain_text_pass_through():
    assert to_ascii("") == ""
    assert to_ascii("nothing to do here") == "nothing to do here"
