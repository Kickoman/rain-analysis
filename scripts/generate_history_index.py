#!/usr/bin/env python3
"""Generate history/index.html from available report files.

Parses actual model performance (best model name + F1 score) from each
report to populate the history cards.
"""

from pathlib import Path
import re


def _extract_best_model(html_content: str) -> str:
    """Extract best model name and F1 score from a report HTML file.

    Handles two report formats:
    1. Pressure variants: 'Best model: name (F1: X.XXX)'
    2. Daily reports: 'Best overall (F-beta=N): name @ T%'
       + leaderboard table containing F1 column.
    """
    # Strip HTML tags for cleaner regex matching
    text = re.sub(r'<[^>]+>', '', html_content)

    # Format 1: Pressure variants report
    m = re.search(r'Best model:\s*([\w_]+)\s+\(F1:\s*([0-9.]+)\)', text)
    if m:
        return f"{m.group(1)} (F1: {m.group(2)})"

    # Format 2: Daily analysis report
    m = re.search(r'Best overall[^:]*:\s*([\w_]+)', text)
    if m:
        model = m.group(1)
        # Try to extract F1 from leaderboard table (match on HTML <td> tags)
        f1_m = re.search(rf'{model}</td>\s*<td>([0-9.]+)', html_content)
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
        html_content = report.read_text()
        best = _extract_best_model(html_content)

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
