"""The landing page must carry the live-widget mount point and script.

The widget itself ships disabled (base: null in live-widget.js) until the
backend has a public hostname; these tests pin the wiring so a template
refactor cannot silently drop it.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
GENERATOR = ROOT / "scripts_utils" / "generate_landing_page.py"
WIDGET_JS = ROOT / "site" / "assets" / "live-widget.js"
STYLE_CSS = ROOT / "site" / "assets" / "style.css"


def test_landing_template_mounts_widget():
    source = GENERATOR.read_text(encoding="utf-8")
    assert '<div id="live-rain-widget"></div>' in source
    assert '<script src="assets/live-widget.js" defer></script>' in source


def test_widget_ships_disabled():
    js = WIDGET_JS.read_text(encoding="utf-8")
    # base: null means the site renders identically to the widget-free site
    assert re.search(r"base:\s*null", js), "widget must ship disabled until a hostname exists"
    assert "live-rain-widget" in js
    assert "/api/v1/data/current" in js
    assert "X-API-Key" in js


def test_widget_styles_present():
    css = STYLE_CSS.read_text(encoding="utf-8")
    assert ".live-widget" in css
