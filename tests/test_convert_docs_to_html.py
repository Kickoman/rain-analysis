"""
Tests for convert_docs_to_html — the docs_site/*.md → docs/*.html converter.

Every file in docs_site/ is now published, not just the glossary. That exposed
their cross-references: `[MODELS.md](MODELS.md)` works on GitHub and 404s on the
site, so relative sibling links are rewritten to the generated pages.
"""

import pytest

from convert_docs_to_html import _rewrite_link, markdown_to_html


# ---------------------------------------------------------------------------
# Link rewriting
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("target,expected", [
    ("MODELS.md", "MODELS.html"),
    ("./BASELINE_MODEL.md", "./BASELINE_MODEL.html"),
    ("CHANGELOG.md#2026-08-13", "CHANGELOG.html#2026-08-13"),
    ("data_sources.MD", "data_sources.html"),
])
def test_sibling_documents_are_rewritten(target, expected):
    assert _rewrite_link(target) == expected


@pytest.mark.parametrize("target", [
    "../README.md",              # not published under docs/
    "docs/other.md",             # different directory
    "https://example.com/a.md",  # external
    "http://example.com/a.md",
    "mailto:someone@example.com",
    "#section",                  # in-page anchor
    "GLOSSARY.html",             # already a page
    "CONTRIBUTING",              # no extension
])
def test_other_targets_are_left_alone(target):
    assert _rewrite_link(target) == target


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def test_link_rewriting_applies_during_conversion():
    html = markdown_to_html("See [the models](MODELS.md) for details.", "Doc")
    assert 'href="MODELS.html"' in html
    assert 'href="MODELS.md"' not in html


def test_external_links_survive_conversion():
    html = markdown_to_html("[repo](https://github.com/Kickoman/rain-analysis)", "Doc")
    assert 'href="https://github.com/Kickoman/rain-analysis"' in html


def test_headings_and_emphasis():
    html = markdown_to_html("# Title\n\n## Section\n\n**bold** and `code`", "Doc")
    assert "<h1>Title</h1>" in html
    assert "<h2>Section</h2>" in html
    assert "<strong>bold</strong>" in html
    assert "<code>code</code>" in html


def test_page_is_well_formed():
    html = markdown_to_html("# Doc", "Doc")
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "</html>" in html.rstrip()
    assert 'lang="en"' in html
