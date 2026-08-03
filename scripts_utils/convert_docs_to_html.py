#!/usr/bin/env python3
"""
Convert markdown documentation files to HTML for gh-pages.
"""

import re
import sys
from pathlib import Path


def markdown_to_html(md_content: str, title: str) -> str:
    """
    Simple markdown to HTML converter.
    Handles: headers, code blocks, lists, links, bold, italic, inline code.
    """
    html_lines = []
    in_code_block = False
    in_list = False
    code_lang = ""
    
    lines = md_content.split('\n')
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Code blocks
        if line.startswith('```'):
            if not in_code_block:
                code_lang = line[3:].strip()
                in_code_block = True
                html_lines.append(f'<pre><code class="language-{code_lang}">')
            else:
                in_code_block = False
                html_lines.append('</code></pre>')
            i += 1
            continue
        
        if in_code_block:
            html_lines.append(line.replace('<', '&lt;').replace('>', '&gt;'))
            i += 1
            continue
        
        # Headers
        if line.startswith('#'):
            level = len(line) - len(line.lstrip('#'))
            text = line.lstrip('#').strip()
            text = apply_inline_formatting(text)
            
            # Close list if open
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            
            html_lines.append(f'<h{level}>{text}</h{level}>')
            i += 1
            continue
        
        # Lists
        if line.strip().startswith('- ') or line.strip().startswith('* '):
            if not in_list:
                html_lines.append('<ul>')
                in_list = True
            text = line.strip()[2:].strip()
            text = apply_inline_formatting(text)
            html_lines.append(f'<li>{text}</li>')
            i += 1
            continue
        
        # Numbered lists
        if re.match(r'^\d+\.\s', line.strip()):
            text = re.sub(r'^\d+\.\s', '', line.strip())
            text = apply_inline_formatting(text)
            if not in_list:
                html_lines.append('<ol>')
                in_list = True
            html_lines.append(f'<li>{text}</li>')
            i += 1
            continue
        
        # Empty line
        if not line.strip():
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            html_lines.append('<br>')
            i += 1
            continue
        
        # Regular paragraph
        if in_list:
            html_lines.append('</ul>')
            in_list = False
        
        text = apply_inline_formatting(line)
        html_lines.append(f'<p>{text}</p>')
        i += 1
    
    # Close any open lists
    if in_list:
        html_lines.append('</ul>')
    
    return '\n'.join(html_lines)


def apply_inline_formatting(text: str) -> str:
    """Apply inline markdown formatting: bold, italic, code, links."""
    # Links: [text](url)
    text = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', text)
    
    # Bold: **text** or __text__
    text = re.sub(r'\*\*([^\*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__([^_]+)__', r'<strong>\1</strong>', text)
    
    # Italic: *text* or _text_
    text = re.sub(r'\*([^\*]+)\*', r'<em>\1</em>', text)
    text = re.sub(r'_([^_]+)_', r'<em>\1</em>', text)
    
    # Inline code: `code`
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    
    return text


def create_html_page(content: str, title: str) -> str:
    """Wrap content in full HTML page."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} — Rain Analysis</title>
    <link rel="stylesheet" href="../assets/style.css">
    <style>
        body {{
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
        }}
        h1, h2, h3, h4 {{
            color: #2c3e50;
            margin-top: 1.5em;
        }}
        h1 {{
            border-bottom: 2px solid #3498db;
            padding-bottom: 0.3em;
        }}
        pre {{
            background: #f6f8fa;
            border: 1px solid #d1d5da;
            border-radius: 6px;
            padding: 16px;
            overflow-x: auto;
        }}
        code {{
            background: #f6f8fa;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 0.9em;
        }}
        pre code {{
            background: none;
            padding: 0;
        }}
        a {{
            color: #3498db;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        .back-link {{
            margin-bottom: 2em;
            display: block;
        }}
        ul, ol {{
            margin: 1em 0;
        }}
        li {{
            margin: 0.5em 0;
        }}
    </style>
</head>
<body>
    <a href="../index.html" class="back-link">← Back to Home</a>
    {content}
</body>
</html>"""


def convert_file(input_path: Path, output_path: Path):
    """Convert a markdown file to HTML."""
    print(f"Converting {input_path.name} → {output_path.name}")
    
    # Read markdown
    md_content = input_path.read_text(encoding='utf-8')
    
    # Extract title from first header or filename
    title = input_path.stem
    first_line = md_content.split('\n')[0]
    if first_line.startswith('#'):
        title = first_line.lstrip('#').strip()
    
    # Convert to HTML
    html_content = markdown_to_html(md_content, title)
    
    # Wrap in full page
    full_html = create_html_page(html_content, title)
    
    # Write output
    output_path.write_text(full_html, encoding='utf-8')
    print(f"  ✅ Created {output_path}")


def main():
    # Define paths
    docs_site = Path('docs_site')
    output_dir = Path('docs_html')
    
    # Create output directory
    output_dir.mkdir(exist_ok=True)
    
    # Files to convert
    files_to_convert = [
        'MODELS.md',
        'BASELINE_MODEL.md',
        'CLI_RUNNER.md',
        'DATA_SOURCES.md',
    ]
    
    print("Converting documentation files...\n")
    
    for filename in files_to_convert:
        input_path = docs_site / filename
        if not input_path.exists():
            print(f"  ⚠️  {filename} not found, skipping")
            continue
        
        output_filename = input_path.stem + '.html'
        output_path = output_dir / output_filename
        
        convert_file(input_path, output_path)
    
    print(f"\n✅ Conversion complete! Files in {output_dir}/")


if __name__ == '__main__':
    main()
