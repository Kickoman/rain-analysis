#!/usr/bin/env python3
"""Convert GLOSSARY.md to HTML for GitHub Pages."""

from pathlib import Path
import re


def markdown_to_html(md_content: str) -> str:
    """Simple markdown to HTML converter for GLOSSARY.md."""
    html = md_content
    
    # Headers
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    
    # Bold
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    
    # Italic
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
    
    # Code inline
    html = re.sub(r'`([^`]+)`', r'<code>\1</code>', html)
    
    # Links [text](url)
    html = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', html)
    
    # Horizontal rules
    html = re.sub(r'^---+$', r'<hr>', html, flags=re.MULTILINE)
    
    # Code blocks
    html = re.sub(r'^```\n(.*?)\n```$', r'<pre><code>\1</code></pre>', html, flags=re.MULTILINE | re.DOTALL)
    
    # Lists (simple unordered)
    html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
    
    # Wrap consecutive <li> in <ul>
    html = re.sub(r'(<li>.*?</li>\n)+', lambda m: '<ul>\n' + m.group(0) + '</ul>\n', html, flags=re.DOTALL)
    
    # Tables - convert markdown tables to HTML
    # Find table blocks (lines starting with |)
    table_pattern = r'((?:^\|.+\|$\n?)+)'
    
    def convert_table(match):
        table_md = match.group(1)
        lines = [line.strip() for line in table_md.strip().split('\n')]
        
        if len(lines) < 2:
            return table_md  # Not a valid table
        
        # First line is header
        header_cells = [cell.strip() for cell in lines[0].split('|')[1:-1]]
        
        # Second line is separator (skip it)
        # Rest are data rows
        data_rows = []
        for line in lines[2:]:
            cells = [cell.strip() for cell in line.split('|')[1:-1]]
            data_rows.append(cells)
        
        # Build HTML table
        html_table = '<table>\n<thead>\n<tr>\n'
        for cell in header_cells:
            html_table += f'<th>{cell}</th>\n'
        html_table += '</tr>\n</thead>\n<tbody>\n'
        
        for row in data_rows:
            html_table += '<tr>\n'
            for cell in row:
                html_table += f'<td>{cell}</td>\n'
            html_table += '</tr>\n'
        
        html_table += '</tbody>\n</table>\n'
        return html_table
    
    html = re.sub(table_pattern, convert_table, html, flags=re.MULTILINE)
    
    # Paragraphs - wrap text blocks in <p>
    lines = html.split('\n')
    result = []
    in_paragraph = False
    paragraph_lines = []
    
    for line in lines:
        stripped = line.strip()
        
        # Check if line is a tag
        is_tag = (
            stripped.startswith('<h') or
            stripped.startswith('<ul') or stripped.startswith('</ul') or
            stripped.startswith('<li') or
            stripped.startswith('<hr') or
            stripped.startswith('<pre') or stripped.startswith('</pre') or
            stripped.startswith('<table') or stripped.startswith('</table') or
            stripped.startswith('<thead') or stripped.startswith('</thead') or
            stripped.startswith('<tbody') or stripped.startswith('</tbody') or
            stripped.startswith('<tr') or stripped.startswith('</tr') or
            stripped.startswith('<th') or stripped.startswith('<td') or
            stripped == ''
        )
        
        if is_tag or stripped == '':
            if in_paragraph and paragraph_lines:
                # Join lines with <br> instead of space to preserve line breaks
                result.append('<p>' + '<br>\n'.join(paragraph_lines) + '</p>')
                paragraph_lines = []
                in_paragraph = False
            if stripped:
                result.append(line)
        else:
            # Regular text line
            in_paragraph = True
            paragraph_lines.append(stripped)
    
    # Close any remaining paragraph
    if in_paragraph and paragraph_lines:
        result.append('<p>' + '<br>\n'.join(paragraph_lines) + '</p>')
    
    return '\n'.join(result)


def main():
    glossary_md = Path("docs/GLOSSARY.md")
    if not glossary_md.exists():
        print("❌ docs/GLOSSARY.md not found")
        return
    
    md_content = glossary_md.read_text()
    body_html = markdown_to_html(md_content)
    
    # Wrap in full HTML page
    full_html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GLOSSARY — ML Metrics</title>
    <link rel="stylesheet" href="../assets/style.css">
    <style>
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 1em 0;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 0.5em;
            text-align: left;
        }}
        th {{
            background-color: #f4f4f4;
            font-weight: bold;
        }}
        code {{
            background-color: #f4f4f4;
            padding: 0.2em 0.4em;
            border-radius: 3px;
            font-family: monospace;
        }}
        pre {{
            background-color: #f4f4f4;
            padding: 1em;
            border-radius: 5px;
            overflow-x: auto;
        }}
        pre code {{
            background-color: transparent;
            padding: 0;
        }}
    </style>
</head>
<body>
    <header>
        <h1>📖 GLOSSARY — Machine Learning Metrics</h1>
        <p>Определения метрик качества моделей</p>
    </header>

    <nav>
        <a href="../index.html">Home</a>
        <a href="../current/index.html">Latest Report</a>
        <a href="../history/index.html">History</a>
        <a href="../metrics/index.html">Metrics Timeline</a>
        <a href="GLOSSARY.html" class="active">Glossary</a>
    </nav>

    <main>
{body_html}
    </main>

    <footer>
        <p>Generated from <a href="https://github.com/Kickoman/rain-analysis/blob/master/docs/GLOSSARY.md">docs/GLOSSARY.md</a></p>
    </footer>
</body>
</html>'''
    
    output_path = Path("docs/GLOSSARY.html")
    output_path.write_text(full_html)
    print(f"✅ Generated {output_path}")


if __name__ == '__main__':
    main()
