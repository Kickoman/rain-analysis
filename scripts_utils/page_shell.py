"""
page_shell.py — the one page every generator renders into.
==========================================================

Until now each of the five generators built its own ``<!DOCTYPE html>`` from an
f-string, so the header, the nav and the footer existed in six copies (seven,
counting the static ``site/404.html``). That is why the nav drifted: history
pages highlighted "Latest Report", every documentation page highlighted
"Glossary", and the metrics page called the same destination "Metrics" while
everyone else called it "Metrics Timeline". None of that was a decision; it was
five files nobody edited together.

This is the shell from the Bare Metal design (``templates/page.html``): the
wordmark header, the lower-case nav, the theme script, the footer. A generator
now supplies only what is actually its own — a title, a subtitle, a body, and
which nav item is current.

Two things in the ``<head>`` are load-bearing and easy to get wrong:

* the inline theme snippet must run **before** the stylesheet paints, or a
  reader who chose the dark theme gets a grey flash on every navigation;
* ``assets/site.js`` is deferred, because it needs the nav to exist before it
  can put the LIGHT|DARK switch into it.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone

from page_head import head_tags

# (href relative to the site root, label, key). The key is what a caller passes
# as ``active`` — labels are display text and change more freely than keys.
NAV: tuple[tuple[str, str, str], ...] = (
    ("index.html", "home", "home"),
    ("current/index.html", "latest report", "current"),
    ("history/index.html", "history", "history"),
    ("metrics/index.html", "metrics timeline", "metrics"),
    ("docs/GLOSSARY.html", "glossary", "docs"),
)

REPO_URL = "https://github.com/Kickoman/rain-analysis"

# The wordmark. CSS prepends "~/" to it, so this is deliberately bare.
WORDMARK = "rain-analysis"

# Straplines, lower case per the design's casing rule.
SUBTITLE_REPORTS = "automated performance tracking and reports"
SUBTITLE_DOCS = "documentation & ml metrics reference"

# Applied before the first paint. Kept on one line because a formatter that
# breaks it would put a parse error between the reader and the page.
_THEME_SNIPPET = (
    "<script>(function(){try{if(localStorage.getItem('ra-theme')==='dark')"
    "document.documentElement.setAttribute('data-theme','dark');}catch(e){}})();</script>"
)


def nav_html(active: str, root: str = "") -> str:
    """The nav bar, with exactly one item marked current.

    An unknown ``active`` marks nothing rather than raising: a page with no
    highlighted nav item is a cosmetic flaw, but a generator that dies here
    takes the whole deploy with it.
    """
    lines = []
    for href, label, key in NAV:
        current = ' class="active"' if key == active else ""
        lines.append(f'        <a href="{root}{href}"{current}>{label}</a>')
    return "\n".join(lines)


def generated_stamp(when: datetime | None = None) -> str:
    """Footer timestamp, lower case and ISO-ish: ``generated: 2026-09-15 11:07 utc``."""
    when = when or datetime.now(timezone.utc)
    return f"generated: {when.strftime('%Y-%m-%d %H:%M')} utc"


def render_page(
    *,
    title: str,
    description: str,
    body: str,
    active: str,
    subtitle: str = SUBTITLE_REPORTS,
    section_class: str | None = None,
    root: str = "",
    extra_head: str = "",
    header_extra: str = "",
    extra_body: str = "",
    generated: str | None = None,
) -> str:
    """Render one complete page.

    ``title`` is the browser-tab title; the page's own heading belongs in
    ``body`` as the first ``<h1>``, because the header ``<h1>`` is the wordmark.

    ``section_class`` wraps the body in a single ``<section>`` — pass ``None``
    when the body already supplies its own sections, as the landing page does.

    ``root`` is the path back to the site root: ``""`` at the root,
    ``"../"`` one level down, ``"/rain-analysis/"`` for a page that can be
    served from any depth.
    """
    stamp = generated if generated is not None else generated_stamp()

    if section_class is None:
        main_body = body
    else:
        main_body = f'        <section class="{section_class}">\n{body}\n        </section>'

    head_extra = f"\n{extra_head}" if extra_head else ""
    head_wordmark = f"\n{header_extra}" if header_extra else ""
    tail = f"\n{extra_body}" if extra_body else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)} — Rain Analysis</title>
    {head_tags(description)}
    <link rel="stylesheet" href="{root}assets/style.css">
    {_THEME_SNIPPET}
    <script src="{root}assets/site.js" defer></script>{head_extra}
</head>
<body>
    <a class="skip-link" href="#main">skip to content</a>

    <header>
        <h1>{WORDMARK}</h1>
        <p>{subtitle}</p>{head_wordmark}
    </header>

    <nav>
{nav_html(active, root)}
    </nav>

    <main id="main">
{main_body}
    </main>

    <footer>
        <p>auto-generated from <a href="{REPO_URL}">rain-analysis</a> — do not edit the gh-pages branch by hand</p>
        <p>{stamp}</p>
    </footer>{tail}
</body>
</html>
"""
