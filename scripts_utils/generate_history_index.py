#!/usr/bin/env python3
"""Generate history/index.html from available report files.

Parses actual model performance (best model name + F1 score) from each
report to populate the history cards.
"""

import sys
from pathlib import Path
import re
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_parse import extract_best_model, leaderboard_f1, strip_tags  # noqa: E402
from page_head import head_tags  # noqa: E402


def _extract_best_model(html_content: str) -> str:
    """Describe the best model of a report as ``name (F1: X.XXX)``.

    Handles two report formats:
    1. Pressure variants: 'Best model: name (F1=X.XXX)' or '(F1: X.XXX)'
    2. Daily reports: 'Best overall (F-beta=N): name @ T%'
       + leaderboard table containing F1 column.

    When the leaderboard reports ``N/A`` for that model the card says so. It used
    to fall through to the Temporal Metrics table and present *that* F1 — a score
    measured under a ±3h tolerance — as if it were the leaderboard's.
    """
    text = strip_tags(html_content)

    # Format 1: Pressure variants report (F1: or F1=)
    m = re.search(r'Best model:\s*([\w_]+)\s+\(F1[:=]\s*([0-9.]+)\)', text)
    if m:
        return f"{m.group(1)} (F1: {m.group(2)})"

    # Format 2: Daily analysis report
    model = extract_best_model(text)
    if model:
        f1_value = leaderboard_f1(html_content, model)
        if f1_value is not None:
            return f"{model} (F1: {f1_value:.3f})"
        return f"{model} (F1: no data)"

    return 'N/A'


def _parse_date_from_filename(filename: str) -> tuple:
    """Parse date from filename, return (date_obj, is_dated, original_filename).
    
    Returns:
        - (datetime.date, True, filename) for dated files like '2026-07-20.html'
        - (None, False, filename) for other files like 'pressure_variants_2026-07-15.html'
    """
    # Try to match pure date filenames: YYYY-MM-DD.html
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})\.html$', filename)
    if m:
        try:
            date = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
            return (date, True, filename)
        except ValueError as e:
            print(f"[WARN] Invalid date in filename {filename}: {e}", file=sys.stderr)
            # Continue processing as non-dated file
    
    return (None, False, filename)


def main():
    history_dir = Path('history')
    if not history_dir.is_dir():
        print("❌ history/ not found — cannot build the history index", file=sys.stderr)
        sys.exit(1)

    all_reports = list(history_dir.glob('*.html'))

    # Separate and sort reports
    dated_reports = []
    other_reports = []
    
    for report in all_reports:
        if report.name == 'index.html':
            continue
        
        date_obj, is_dated, _ = _parse_date_from_filename(report.name)
        if is_dated:
            dated_reports.append((date_obj, report))
        else:
            other_reports.append(report)
    
    # Sort dated reports by date (newest first)
    dated_reports.sort(key=lambda x: x[0], reverse=True)
    
    # Sort other reports lexicographically (newest first)
    other_reports.sort(key=lambda x: x.name, reverse=True)
    
    # Build cards: dated first, then others
    cards = []
    
    for date_obj, report in dated_reports:
        date = report.stem
        html_content = report.read_text()
        best = _extract_best_model(html_content)

        cards.append(f'''                <div class="card">
                    <h3>{date}</h3>
                    <p>Best model: {best}</p>
                    <a href="{report.name}">View Report →</a>
                </div>''')
    
    for report in other_reports:
        date = report.stem
        html_content = report.read_text()
        best = _extract_best_model(html_content)

        cards.append(f'''                <div class="card">
                    <h3>{date}</h3>
                    <p>Best model: {best}</p>
                    <a href="{report.name}">View Report →</a>
                </div>''')

    if not cards:
        # A well-formed page with zero cards used to be written with exit 0, so a
        # run where the report checkout produced nothing would quietly replace the
        # History index with a blank one.
        print("❌ No reports found in history/ — refusing to write an empty index",
              file=sys.stderr)
        sys.exit(1)

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>History — Rain Analysis</title>
    {head_tags("Every daily rain-model analysis report, newest first.")}
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
        <a href="../docs/GLOSSARY.html">Glossary</a>
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
