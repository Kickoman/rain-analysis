"""The shell every generated page renders into.

Six generators used to build their own ``<!DOCTYPE html>``, which is how the
nav came to disagree with itself: history pages highlighted "Latest Report",
every documentation page highlighted "Glossary". These tests pin the parts
that are easy to break from a distance — the relative root, the single active
item, and the two ``<head>`` elements the theme depends on.
"""

import re

import pytest

import page_shell
from page_shell import NAV, nav_html, render_page


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("_, __, key", NAV)
def test_exactly_one_item_is_current(_, __, key):
    html = nav_html(key)
    assert html.count('class="active"') == 1
    assert f'{[h for h, _l, k in NAV if k == key][0]}"' in html


def test_unknown_active_marks_nothing():
    """A cosmetic flaw beats a generator that dies and takes the deploy with it."""
    assert 'class="active"' not in nav_html("no-such-page")


@pytest.mark.parametrize("root", ["", "../", "/rain-analysis/"])
def test_root_prefixes_every_link(root):
    html = nav_html("home", root)
    for href, _label, _key in NAV:
        assert f'href="{root}{href}"' in html


def test_nav_labels_are_lower_case():
    """The design's casing rule, applied to chrome we generate ourselves."""
    for _href, label, _key in NAV:
        assert label == label.lower(), label


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

def _page(**kwargs):
    base = dict(title="Example", description="A description.",
                body="        <section><p>body</p></section>", active="home")
    return render_page(**{**base, **kwargs})


def test_title_keeps_its_suffix():
    assert "<title>Example — Rain Analysis</title>" in _page()


def test_title_is_escaped():
    assert "<title>A &amp; B — Rain Analysis</title>" in _page(title="A & B")


def test_theme_is_applied_before_the_stylesheet_paints():
    """Otherwise a dark reader gets a grey flash on every navigation."""
    html = _page()
    snippet = html.index("localStorage.getItem('ra-theme')")
    assert snippet > html.index("assets/style.css")
    assert snippet < html.index("<body>")


def test_site_js_is_deferred():
    """It needs the nav to exist before it can put the theme switch into it."""
    assert re.search(r'<script src="[^"]*assets/site\.js" defer></script>', _page())


@pytest.mark.parametrize("root", ["", "../", "/rain-analysis/"])
def test_assets_follow_the_root(root):
    html = _page(root=root)
    assert f'href="{root}assets/style.css"' in html
    assert f'src="{root}assets/site.js"' in html


def test_body_is_wrapped_only_when_asked():
    assert '<section class="report-content">' in _page(section_class="report-content")
    assert 'class="report-content"' not in _page()


def test_page_has_one_header_and_one_main():
    html = _page()
    assert html.count("<main id=\"main\">") == 1
    assert html.count("<header>") == 1
    assert html.count("</html>") == 1


def test_extras_land_where_they_belong():
    html = _page(extra_head="    <script src=x></script>",
                 header_extra='        <div id="live-rain-widget"></div>',
                 extra_body='    <script src=y></script>')
    assert html.index("src=x") < html.index("</head>")
    assert html.index("live-rain-widget") < html.index("</header>")
    assert html.index("src=y") > html.index("</footer>")


def test_generated_stamp_can_be_pinned():
    """So a test — or a reproducible build — is not at the mercy of the clock."""
    assert "generated: frozen" in _page(generated="generated: frozen")


def test_stamp_is_lower_case_and_dated():
    assert re.match(r"generated: \d{4}-\d{2}-\d{2} \d{2}:\d{2} utc$",
                    page_shell.generated_stamp())
