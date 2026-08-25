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


def test_widget_configuration():
    js = WIDGET_JS.read_text(encoding="utf-8")
    # Deployed 2026-08-25: base points at the kfrank backend behind nginx.
    # The embedded key is a PUBLIC read-only key by design (#407).
    assert 'base: "https://www.kanstancin.net/rain-api"' in js
    assert re.search(r'key:\s*"ra_live_[0-9a-f]+"', js)
    assert "live-rain-widget" in js
    assert "/api/v1/data/current" in js
    assert "X-API-Key" in js


def test_widget_styles_present():
    css = STYLE_CSS.read_text(encoding="utf-8")
    assert ".live-widget" in css
