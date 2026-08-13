"""
page_head.py — the ``<head>`` tags every generated page should carry.
=====================================================================

Six generators build their own ``<!DOCTYPE html> … <head>`` block, so anything
that belongs on every page has to be added in six places — which is why none of
them had a description or a favicon. This is the shared piece; a full page-shell
refactor (one ``render_page()`` for header, nav and footer too) is still worth
doing, but this covers what was actually missing.

The favicon is an inline SVG data URI: no extra request, no file to copy to
gh-pages, and no 404 in the console on every page load.
"""

from __future__ import annotations

import html

# 🌧️ as an SVG document, URL-escaped just enough to sit inside an attribute.
FAVICON = (
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E"
    "%3Ctext y='.9em' font-size='90'%3E%F0%9F%8C%A7%EF%B8%8F%3C/text%3E%3C/svg%3E"
)


def head_tags(description: str) -> str:
    """Description and favicon, indented to sit inside an existing ``<head>``."""
    return (
        f'<meta name="description" content="{html.escape(description, quote=True)}">\n'
        f'    <link rel="icon" href="{FAVICON}">'
    )
