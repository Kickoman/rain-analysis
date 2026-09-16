"""
page_head.py — the ``<head>`` tags every generated page should carry.
=====================================================================

The two tags that are page-specific but boilerplate: the meta description and
the favicon. ``page_shell.render_page()`` composes them into the full document
along with the stylesheet, the theme snippet and ``site.js``; this module just
owns the two bits that take an argument.

The favicon is an inline SVG data URI: no extra request, no file to copy to
gh-pages, and no 404 in the console on every page load.
"""

from __future__ import annotations

import html

# A black square with a green "~", the design system's wordmark glyph. It used
# to be the rain-cloud emoji; the design has no emoji in it anywhere, and a tab
# strip is the one place the rule is hardest to walk back later.
FAVICON = (
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E"
    "%3Crect width='16' height='16' fill='%23000'/%3E"
    "%3Ctext x='2' y='12' font-family='monospace' font-size='11' fill='%2300ff00'%3E~%3C/text%3E"
    "%3C/svg%3E"
)


def head_tags(description: str) -> str:
    """Description and favicon, indented to sit inside an existing ``<head>``."""
    return (
        f'<meta name="description" content="{html.escape(description, quote=True)}">\n'
        f'    <link rel="icon" href="{FAVICON}">'
    )
