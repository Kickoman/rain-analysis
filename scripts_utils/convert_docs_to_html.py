#!/usr/bin/env python3
"""
Convert documentation files from docs/ to HTML for GitHub Pages
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
from page_shell import SUBTITLE_DOCS, render_page  # noqa: E402

def _rewrite_link(target: str) -> str:
    """Point relative links at sibling documents to their generated pages.

    Every file in docs_site/ is published as docs/<name>.html, so a relative
    `*.md` target resolves on the site once the extension is swapped. External
    URLs, anchors and paths that leave the directory are left alone.
    """
    if re.match(r'^[a-z][a-z0-9+.-]*:', target, re.IGNORECASE) or target.startswith('#'):
        return target
    path, _, fragment = target.partition('#')
    if not path.lower().endswith('.md'):
        return target
    # Same-directory targets only. `../README.md` and `docs/other.md` point
    # outside docs_site/ and have no generated page to link to.
    bare = path[2:] if path.startswith('./') else path
    if '/' in bare:
        return target
    return f"{path[:-3]}.html" + (f"#{fragment}" if fragment else "")


def markdown_to_html(md_content, title="Documentation", active=""):
    """Convert markdown to HTML with doc-specific styling"""
    # Fenced code comes out first. It used to be handled last, long after the
    # inline-code pass had eaten its backticks and the heading pass had turned
    # every "# comment" line inside it into an <h1>: MODELS.md has seventeen
    # fenced blocks and produced zero <pre> elements and thirty-five bogus
    # headings.
    # Glyphs first, fences second. Code samples here quote real automation
    # YAML and real report output, emoji and all — and the design has no
    # exemption for "inside a code block". Substitution never touches
    # whitespace, so the samples keep their indentation.
    md_content = to_ascii(md_content)
    md_content, fences = protect_fences(md_content)
    md_content = lift_blockquotes(md_content)

    # Escape HTML entities in raw content first
    html_content = html.escape(md_content)
    
    # Headers
    html_content = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', html_content, flags=re.MULTILINE)
    
    # Bold
    html_content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_content)

    # Italics — after bold, so ** markers are already consumed
    html_content = apply_inline(html_content)
    
    # Inline code
    html_content = re.sub(r'`(.+?)`', r'<code>\1</code>', html_content)
    
    # Links. Relative *.md targets are siblings in docs_site/ that get published
    # alongside this page, so point them at the generated .html — on the site a
    # link to MODELS.md is a 404, however well it works on GitHub.
    html_content = re.sub(
        r'\[(.+?)\]\((.+?)\)',
        lambda m: f'<a href="{_rewrite_link(m.group(2))}">{m.group(1)}</a>',
        html_content,
    )
    
    # Horizontal rules — table separators start with '|' and are untouched
    html_content = convert_horizontal_rules(html_content)

    # Tables
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
            
            # Detect if this is header row (check next line for separator)
            is_header = False
            if i + 1 < len(lines) and re.match(r'\|[\s:-]+\|', lines[i+1]):
                is_header = True
            
            if is_header:
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

    # Bullet lists
    html_content = convert_lists(html_content)

    
    # Paragraphs - split by double newlines, but preserve existing HTML tags
    paragraphs = html_content.split('\n\n')
    processed = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        # Don't wrap if it's already HTML
        if p.startswith('<') or '\n<' in p:
            processed.append(p)
        else:
            # Replace single newlines with <br> inside paragraphs
            p = p.replace('\n', '<br>\n')
            processed.append(f'<p>{p}</p>')
    
    html_content = '\n\n'.join(processed)
    
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
        description=f"{title} — documentation for the rain-analysis project.",
        subtitle=SUBTITLE_DOCS,
        body=html_content,
        section_class="docs-content",
        active=active,
        root="../",
    )
    return full_html


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python convert_docs_to_html.py input.md output.html")
        sys.exit(1)
    
    input_file = Path(sys.argv[1])
    output_file = Path(sys.argv[2])
    
    if not input_file.exists():
        print(f"Error: {input_file} not found")
        sys.exit(1)
    
    md_content = input_file.read_text()
    title = input_file.stem
    
    # Only the glossary is in the nav, so only it may claim to be current —
    # every documentation page used to highlight it.
    active = "docs" if input_file.stem == "GLOSSARY" else ""
    html_output = markdown_to_html(md_content, title, active=active)
    
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html_output)
    
    print(f"[ok] generated: {output_file}")
