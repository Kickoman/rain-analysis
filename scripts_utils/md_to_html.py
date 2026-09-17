#!/usr/bin/env python3
"""
Convert Markdown reports to HTML for GitHub Pages
"""
import html
import re
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glyphs import to_ascii  # noqa: E402
from markdown_lite import (  # noqa: E402
    add_heading_ids,
    apply_inline,
    build_toc,
    convert_horizontal_rules,
    convert_lists,
    lift_blockquotes,
    protect_fences,
    render_notices,
    restore_fences,
)
from page_shell import SUBTITLE_REPORTS, render_page  # noqa: E402


def markdown_to_html(md_content, title="Report", active="history"):
    """Convert simple markdown to HTML"""
    # Fenced code first, so nothing downstream sees its backticks or its "#"
    # comment lines, and glyph substitution leaves code verbatim.
    # Emoji become ASCII here, on raw markdown and before escaping, so a
    # replacement can never introduce an unescaped angle bracket. Fences are
    # protected after that, so nothing downstream sees their backticks or the
    # "#" comment lines inside them.
    md_content = to_ascii(md_content)
    md_content, fences = protect_fences(md_content)
    md_content = lift_blockquotes(md_content)

    # Escape HTML entities in raw content first
    html_content = html.escape(md_content)
    
    # Headers
    html_content = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html_content, flags=re.MULTILINE)
    
    # Bold
    html_content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_content)

    # Italics — after bold, so ** markers are already consumed
    html_content = apply_inline(html_content)

    # Code blocks
    html_content = re.sub(r'`(.+?)`', r'<code>\1</code>', html_content)

    # Links
    html_content = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', html_content)

    # Horizontal rules — table separators start with '|' and are untouched
    html_content = convert_horizontal_rules(html_content)

    # Tables - basic conversion
    lines = html_content.split('\n')
    new_lines = []
    in_table = False
    
    for i, line in enumerate(lines):
        if '|' in line and line.strip().startswith('|'):
            if not in_table:
                new_lines.append('<div class="table-wrap">')
                new_lines.append('<table>')
                in_table = True
            
            # Check if it's separator line
            if re.match(r'\|[\s:-]+\|', line):
                continue
            
            cells = [c.strip() for c in line.split('|')[1:-1]]
            
            # First row after table start is header
            if i > 0 and '|' not in lines[i-1]:
                new_lines.append('<thead><tr>')
                for cell in cells:
                    new_lines.append(f'<th>{cell}</th>')
                new_lines.append('</tr></thead><tbody>')
            else:
                new_lines.append('<tr>')
                for cell in cells:
                    new_lines.append(f'<td>{cell}</td>')
                new_lines.append('</tr>')
        else:
            if in_table:
                new_lines.append('</tbody></table></div>')
                in_table = False
            new_lines.append(line)
    
    if in_table:
        new_lines.append('</tbody></table></div>')
    
    html_content = '\n'.join(new_lines)

    # Bullet lists — after the table pass rebuilds the lines, before paragraphs
    # wrap them. Reports are full of these ("Source data ranges", "Ground truth
    # distribution"); without this they rendered as literal "- text".
    html_content = convert_lists(html_content)

    # Paragraphs - split by double newlines, but preserve single newlines as <br>
    paragraphs = html_content.split('\n\n')
    processed = []
    for p in paragraphs:
        p = p.strip()
        if p and not p.startswith('<'):
            # Replace single newlines with <br> within paragraphs
            p_with_br = p.replace('\n', '<br>\n')
            processed.append(f'<p>{p_with_br}</p>')
        else:
            processed.append(p)
    
    html_content = '\n\n'.join(processed)
    
    # Contents block and heading anchors. `report_parse` matches headings as
    # `<h2[^>]*>`, so the added id is invisible to it.
    html_content, headings = add_heading_ids(html_content)
    toc = build_toc(headings)
    if toc:
        marker = "</h1>"
        cut = html_content.find(marker)
        if cut == -1:
            html_content = f"{toc}\n{html_content}"
        else:
            cut += len(marker)
            html_content = f"{html_content[:cut]}\n{toc}{html_content[cut:]}"

    html_content = render_notices(html_content)
    html_content = restore_fences(html_content, fences, html.escape)

    full_html = render_page(
        title=title,
        description="Daily rain prediction model analysis report.",
        subtitle=SUBTITLE_REPORTS,
        body=html_content,
        section_class="report-content",
        active=active,
        root="../",
    )
    return full_html


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python md_to_html.py input.md output.html")
        sys.exit(1)
    
    input_file = Path(sys.argv[1])
    output_file = Path(sys.argv[2])
    
    if not input_file.exists():
        print(f"Error: {input_file} not found")
        sys.exit(1)
    
    md_content = input_file.read_text()
    title = input_file.stem.replace('-', '/')
    
    # current/index.html is the same render as a history page; only the nav
    # differs, and it used to claim "latest report" was current on both.
    active = "current" if output_file.parent.name == "current" else "history"
    html_output = markdown_to_html(md_content, title, active=active)
    
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html_output)
    
    print(f"[ok] generated: {output_file}")
