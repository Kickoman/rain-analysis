#!/usr/bin/env python3
"""Generate metrics/index.html with performance trends from history reports.

Parses all available history HTML reports, extracts the best model and its
F1/Precision/Recall metrics, and renders an up-to-date timeline table.
"""

from pathlib import Path
import re
import json
from datetime import datetime


def _strip_tags(html: str) -> str:
    """Remove HTML tags for plain-text regex matching."""
    return re.sub(r'<[^>]+>', '', html)


def _extract_report_data(html_content: str) -> dict | None:
    """Extract performance data from a daily report HTML.

    Returns a dict with: date, best_model, best_f1, best_precision, best_recall,
    and a list of all model rows.
    """
    text = _strip_tags(html_content)

    # Extract date from title
    date_m = re.search(r'Daily Model Analysis[^—]*[—–-]\s*(\d{4}-\d{2}-\d{2})', text)
    if not date_m:
        return None
    date = date_m.group(1)

    # Extract "Best overall (F-beta=N): name @ T%"
    best_overall_m = re.search(r'Best overall[^:]*:\s*([\w_]+)', text)
    best_model = best_overall_m.group(1) if best_overall_m else None

    # Parse all model rows from HTML table
    # Pattern: <tr><td>model</td><td>F1</td><td>Precision</td><td>Recall</td><td>...</td></tr>
    model_rows = []
    row_pattern = re.compile(
        r'<tr>\s*<td>([\w_]+)</td>\s*<td>([0-9.]+(?:e[+-]?\d+)?)</td>\s*<td>([0-9.]+(?:e[+-]?\d+)?)</td>\s*<td>([0-9.]+(?:e[+-]?\d+)?)</td>',
        re.IGNORECASE
    )

    for m in row_pattern.finditer(html_content):
        model_name = m.group(1)
        f1 = float(m.group(2))
        precision = float(m.group(3))
        recall = float(m.group(4))
        model_rows.append({
            'model': model_name,
            'f1': f1,
            'precision': precision,
            'recall': recall
        })

    if not model_rows:
        return None

    # Find best model by F-beta score (use the declared best_overall if available,
    # otherwise fall back to highest F1)
    best_data = None
    if best_model:
        for row in model_rows:
            if row['model'] == best_model:
                best_data = row
                break

    if not best_data:
        # Fallback: highest F1
        best_data = max(model_rows, key=lambda r: r['f1'])

    return {
        'date': date,
        'best_model': best_data['model'],
        'best_f1': best_data['f1'],
        'best_precision': best_data['precision'],
        'best_recall': best_data['recall'],
        'all_models': model_rows
    }


def main():
    history_dir = Path('history')
    if not history_dir.exists():
        print("❌ history/ directory not found — skipping metrics page")
        return

    reports = sorted(history_dir.glob('*.html'))

    metrics_data = []
    for report in reports:
        if report.name == 'index.html':
            continue
        data = _extract_report_data(report.read_text())
        if data:
            metrics_data.append(data)

    if not metrics_data:
        print("❌ No report data found — skipping metrics page")
        return

    # Sort by date ascending (oldest first for timeline)
    metrics_data.sort(key=lambda d: d['date'])

    # Build table rows (newest first for display)
    rows = []
    for d in reversed(metrics_data):
        rows.append(
            f'                    <tr>\n'
            f'                        <td>{d["date"]}</td>\n'
            f'                        <td>{d["best_model"]}</td>\n'
            f'                        <td class="metric">{d["best_f1"]:.3f}</td>\n'
            f'                        <td class="metric">{d["best_precision"]:.3f}</td>\n'
            f'                        <td class="metric">{d["best_recall"]:.3f}</td>\n'
            f'                    </tr>'
        )

    # Collect all unique model names across reports (for trend data)
    all_models = set()
    for d in metrics_data:
        for m in d['all_models']:
            all_models.add(m['model'])

    # Build JSON data for potential interactive charts
    chart_json = json.dumps(metrics_data, indent=2)

    last_updated = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Metrics Timeline — Rain Analysis</title>
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
        <a href="../history/index.html">History</a>
        <a href="../metrics/index.html" class="active">Metrics Timeline</a>
    </nav>

    <main>
        <section>
            <h2>📈 Performance Metrics Over Time</h2>
            <p>Track how model performance evolves. Data is extracted from daily reports.</p>

            <h3>All Reports ({len(metrics_data)} days)</h3>
            <table>
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Best Model</th>
                        <th>F1 Score</th>
                        <th>Precision</th>
                        <th>Recall</th>
                    </tr>
                </thead>
                <tbody>
{chr(10).join(rows)}
                </tbody>
            </table>

            <p><em>Last updated: {last_updated}. Interactive charts will be added in future updates.</em></p>
        </section>
    </main>

    <footer>
        <p>Auto-generated from <a href="https://github.com/Kickoman/rain-analysis">rain-analysis</a> repository</p>
    </footer>
</body>
</html>'''

    Path('metrics/index.html').write_text(html)
    print(f'✅ Generated metrics/index.html — {len(metrics_data)} reports ({metrics_data[0]["date"]} to {metrics_data[-1]["date"]})')


if __name__ == '__main__':
    main()
