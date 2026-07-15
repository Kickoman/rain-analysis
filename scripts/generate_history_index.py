#!/usr/bin/env python3
"""Generate history/index.html from available report files."""

from pathlib import Path
import re


def main():
    history_dir = Path('history')
    reports = sorted(history_dir.glob('*.html'), reverse=True)
    
    cards = []
    for report in reports:
        if report.name == 'index.html':
            continue
        date = report.stem
        # Read first few lines to extract best model
        content = report.read_text()
        match = re.search(r'Best overall.*?:\s*(\w+)', content)
        model = match.group(1) if match else 'N/A'
        
        cards.append(f'''                <div class="card">
                    <h3>{date}</h3>
                    <p>Best model: {model}</p>
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
