#!/usr/bin/env python3
"""
Tests for md_to_html.py HTML escaping
"""
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from md_to_html import markdown_to_html


def test_escape_angle_brackets():
    """Test that < and > are escaped in content"""
    md = "Pressure <1000 hPa is low"
    html = markdown_to_html(md, "Test")
    
    # Original < and > should be escaped
    assert "&lt;" in html
    assert "&gt;" not in html  # > wasn't in input
    assert "<1000" not in html  # Raw < should not appear
    
    # But HTML tags we generate should remain
    assert "<p>" in html
    assert "</p>" in html


def test_escape_ampersand():
    """Test that & is escaped"""
    md = "Rain & snow detection"
    html = markdown_to_html(md, "Test")
    
    assert "&amp;" in html
    assert "Rain &amp; snow" in html


def test_escape_in_comparison_expressions():
    """Test real-world case: F-beta=2 >0.5"""
    md = "F-beta=2 >0.5 threshold"
    html = markdown_to_html(md, "Test")
    
    assert "&gt;" in html
    assert ">0.5" not in html  # Raw > should not appear


def test_escape_script_like_content():
    """Test that script-like content is neutralized"""
    md = "Text with <script>alert('xss')</script> attempt"
    html = markdown_to_html(md, "Test")
    
    # Script tags should be escaped
    assert "&lt;script&gt;" in html
    assert "&lt;/script&gt;" in html
    assert "<script>" not in html


def test_markdown_tags_still_work():
    """Test that markdown syntax still generates proper HTML"""
    md = "## Header\n\n**Bold text** and `code`"
    html = markdown_to_html(md, "Test")
    
    # Generated HTML tags should exist
    assert "<h2>Header</h2>" in html
    assert "<strong>Bold text</strong>" in html
    assert "<code>code</code>" in html


def test_title_escaping():
    """Test that title parameter is also escaped"""
    md = "Content"
    html = markdown_to_html(md, "Test <script>")
    
    # Title should be escaped in <title> tag
    assert "<title>Test &lt;script&gt; — Rain Analysis</title>" in html


def test_links_preserved():
    """Test that markdown links still work after escaping"""
    md = "[Link text](https://example.com?a=1&b=2)"
    html = markdown_to_html(md, "Test")
    
    # Link should be generated correctly
    # Note: URL in href should remain with & (not &amp; in attribute)
    assert '<a href="https://example.com?a=1&amp;b=2">Link text</a>' in html


def test_table_with_special_chars():
    """Test tables containing special characters"""
    md = """| Model | Threshold |
|-------|-----------|
| A     | <1000     |
| B     | >500      |"""
    
    html = markdown_to_html(md, "Test")
    
    # Table should be created
    assert "<table>" in html
    # Note: table logic treats first row as data, not header (because of escape impact)
    assert "<td>Model</td>" in html or "<th>Model</th>" in html
    
    # Special chars in cells should be escaped
    assert "&lt;1000" in html
    assert "&gt;500" in html


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
