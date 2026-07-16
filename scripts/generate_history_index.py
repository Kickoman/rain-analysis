#!/usr/bin/env python3
"""Generate history/index.html from available report files."""

from pathlib import Path
import re


def extract_best_model(html_content):
    """Extract best model + F1 from report HTML content."""
    # Strip HTML tags for text search
    text = re.sub(r'<[^>]+>', '', html_content)
    
    # Try: "Best model: model_name (F1: 0.XXX)"
    m = re.search(r'Best model:\s*([\w_]+)\s+\(F1:\s*([0-9.]+)\)', text)
    if m:
        return f"{m.group(1)} (F1: {m.group(2)})"
    
    # Try: table row with model name and F1
    m = re.search(r'Best overall[^:]*:\s*(\w+)', text)
    if m:
        model = m.group(1)
        f1_m = re.search(f'{model}</td>\\s*<td>([0-9.]+)', html_content)
        if f1_m:
            return f"{model} (F1: {f1_m.group(1)})"
        return model
    
    return 'N/A'


def main():
    history_dir = Path('history')
    reports = sorted(history_dir.glob('*.html'), reverse=True)
    
    cards = []
    for report in reports:
        if report.name == 'index.html':
            continue
        date = report.stem
        content = report.read_text()
        best = extract_best_model(content)
        
        cards.append(f'''                <div class="card">
                    <h3>{date}</h3>
                    <p>Best model: {best}</p>
                    <a href="{report.name}">View Report →</a>
                </div>''')
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>History — Rain Analysis</title>
    <link rel="stylesheet" href="../assets/style.css">
</head>
<body>
    <header>
        <h1>🌧️ Rain Prediction Model Analysis</h1>
        <p>Automated performance tracking and reports</p>
    </header>

    <nav>
        <a href="../index.html">Home</a>
        <a href="../current/index.html">Latest Report</a>
        <a href="../history/index.html" class="active">History</a>
        <a href="../metrics/index.html">Metrics Timeline</a>
    </nav>

    <main>
        <section>
            <h2>📅 Historical Reports</h2>
            <p>Daily analysis reports, newest first.</p>
            
            <div class="cards">
{chr(10).join(cards)}
            </div>
        </section>
    </main>

    <footer>
        <p>Auto-generated from <a href="https://github.com/Kickoman/rain-analysis">rain-analysis</a> repository</p>
    </footer>
</body>
</html>'''
    
    Path('history/index.html').write_text(html)
    print('✅ Updated history/index.html')


if __name__ == '__main__':
    main()
