"""
glyphs.py — emoji out, ASCII status glyphs in, at render time only.
===================================================================

The Bare Metal design system has no emoji in it anywhere: status is carried by
bracketed ASCII (``[ok] [!] [x] [i]``) and ``>`` markers, because the whole
look is a late-2000s terminal page and a colour pictograph breaks it on sight.

**This runs when the site is built, not when a report is written.** The
markdown in ``reports/`` keeps its emoji: it is the data source, it is read on
GitHub where emoji render fine, and rewriting 61 committed reports to change
how a web page looks would be the tail wagging the dog.

Two consequences of that split, both deliberate:

* ``report_parse`` decodes the verdict column *by glyph*, and after this runs
  the published HTML says ``[ok]`` where the markdown says ``✅``. Its
  ``_VERDICT_MARK`` therefore accepts both spellings — the ASCII forms for
  pages built from now on, the emoji for every page already on gh-pages.
* ``generate_landing_page._is_failed_experiment()`` tests
  ``MODEL_DESCRIPTIONS[...].startswith("❌")``. That table keeps its emoji;
  only the rendered string passes through here.

Characters deliberately **not** touched: ``—``, ``–``, ``…``, ``·``, ``≥``,
``×``, ``°``. Those are typography and data, not pictographs — ``report_parse``
reads confidence intervals across an en dash and treats ``—`` as a null token,
so replacing them would quietly change numbers rather than decoration.
"""

from __future__ import annotations

# Variation selector 16 — the invisible codepoint that turns a character into
# its emoji presentation. Several sources carry it, several do not, so every
# affected key is registered both ways rather than trusting the input.
_VS16 = "️"

# Longest first: "📈 improving" must win over "📈" or the trend cell ends up
# reading "IMPROVING improving".
_PHRASES: tuple[tuple[str, str], ...] = (
    ("📈 improving", "IMPROVING"),
    ("📉 degrading", "DEGRADING"),
    ("➡️ stable", "STABLE"),
    ("⚪ no data", "[ ] no data"),
)

# Status glyphs. These carry meaning, so they become bracketed ASCII rather
# than disappearing.
_STATUS: dict[str, str] = {
    "✅": "[ok]",
    "❌": "[x]",
    "⚠️": "[!]",
    "⛔": "[x]",
    "ℹ️": "[i]",
    "✓": "[ok]",
    "✗": "[x]",
    # The onset scoreboard's "ranks above chance but has no usable threshold".
    # The design's own table does not cover it; "[~]" reads as "partly", which
    # is what the verdict means.
    "◐": "[~]",
    "🔄": "[~]",
    "⚪": "[ ]",
    "📉": "DEGRADING",
    "📈": "IMPROVING",
    "➡️": "STABLE",
}

# Decoration. Nothing is lost by deleting these; the words beside them already
# said it.
_DECORATIVE = ("🌧️", "📊", "📅", "📚", "📖", "📝", "🤖", "⚙️", "💾", "🔧")

# Arrows. These mostly sit inside prose ("2026-07-01 ... → ...") and inside
# link labels. ASCII "->" keeps both readable; the bare ">" the design uses as
# a list marker is supplied by CSS (``.btn::before``), not by text.
_ARROWS: dict[str, str] = {
    "→": "->",
    "←": "<-",
    "↑": "^",
    "↓": "v",
}


def _both_forms(glyph: str) -> tuple[str, ...]:
    """A glyph with and without its variation selector, longest first."""
    bare = glyph.replace(_VS16, "")
    if bare == glyph:
        return (glyph, glyph + _VS16) if len(glyph) == 1 else (glyph,)
    return (glyph, bare)


def _build_table() -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = list(_PHRASES)
    for source, replacement in {**_STATUS, **_ARROWS}.items():
        for form in _both_forms(source):
            pairs.append((form, replacement))
    for glyph in _DECORATIVE:
        for form in _both_forms(glyph):
            # The trailing space goes with the glyph, or deleting the cloud from
            # "🌧️ Will it rain?" leaves a leading space. Registered first, and
            # the sort below keeps it first, so the bare form only matches a
            # glyph that had nothing after it.
            pairs.append((form + " ", ""))
            pairs.append((form, ""))
    # Longest source first so a phrase is never eaten by one of its own glyphs.
    return tuple(sorted(pairs, key=lambda pair: -len(pair[0])))


TABLE = _build_table()


def to_ascii(text: str) -> str:
    """Replace every emoji the site can emit with its ASCII equivalent.

    Whitespace is never touched beyond the single space that followed a
    deleted decorative glyph. That restraint is the point: this runs over
    markdown that still contains fenced code and the aligned terminal status
    block, where collapsing runs of spaces would destroy the content it was
    meant to tidy.
    """
    for source, replacement in TABLE:
        if source in text:
            text = text.replace(source, replacement)
    return text
