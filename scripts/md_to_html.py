#!/usr/bin/env python3
"""
Convert Markdown reports to HTML for GitHub Pages
"""
import html
import re
import sys
from pathlib import Path
from datetime import datetime

def markdown_to_html(md_content, title="Report"):
    """Convert simple markdown to HTML"""
    # Escape HTML entities in raw content first
    html_content = html.escape(md_content)
    
    # Headers
    html_content = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html_content, flags=re.MULTILINE)
    
    # Bold
    html_content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_content)
    
    # Code blocks
    html_content = re.sub(r'`(.+?)`', r'<code>\1</code>', html_content)
    
    # Links
    html_content = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', html_content)
    
    # Tables - basic conversion
    lines = html_content.split('\n')
    new_lines = []
    in_table = False
    
    for i, line in enumerate(lines):
        if '|' in line and line.strip().startswith('|'):
            if not in_table:
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
                new_lines.append('</tbody></table>')
                in_table = False
            new_lines.append(line)
    
    if in_table:
        new_lines.append('</tbody></table>')
    
    html_content = '\n'.join(new_lines)
    
    # Paragraphs - split by double newlines
    paragraphs = html_content.split('\n\n')
    processed = []
    for p in paragraphs:
        p = p.strip()
        if p and not p.startswith('<'):
            processed.append(f'<p>{p}</p>')
        else:
            processed.append(p)
    
    html_content = '\n\n'.join(processed)
    
    # Build full HTML
    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)} — Rain Analysis</title>
    <link rel="stylesheet" href="../assets/style.css">
</head>
<body>
    <header>
        <h1>🌧️ Rain Prediction Model Analysis</h1>
        <p>Automated performance tracking and reports</p>
    </header>

    <nav>
        <a href="../index.html">Home</a>
        <a href="../current/index.html" class="active">Latest Report</a>
        <a href="../history/index.html">History</a>
        <a href="../metrics/index.html">Metrics Timeline</a>
    </nav>

    <main>
        <section class="report-content">
{html_content}
        </section>
    </main>

    <footer>
        <p>Auto-generated from <a href="https://github.com/Kickoman/rain-analysis">rain-analysis</a> repository</p>
        <p>Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p>
    </footer>
</body>
</html>
"""
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
    
    html_output = markdown_to_html(md_content, title)
    
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html_output)
    
    print(f"✅ Generated: {output_file}")
