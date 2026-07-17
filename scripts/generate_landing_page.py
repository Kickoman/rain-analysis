#!/usr/bin/env python3
"""Generate root index.html (landing page) from the latest daily report.

Reads current/index.html, extracts the best model + date, and produces
a landing page with up-to-date model descriptions and latest results.
"""

from pathlib import Path
import re
from datetime import datetime


# Single source of truth for model descriptions
MODEL_DESCRIPTIONS = {
    "original":           "Baseline v0.1 — dew-point spread + trend (F1=0.440)",
    "tuned":              "Grid-search optimized parameters (F1=0.441)",
    "trend_dominant":     "❌ Failed experiment — trend-primary (F1=0.115, worst)",
    "ha_live":            "✅ Production — deployed in Home Assistant (F1=0.484)",
    "pressure_aware":     "Pressure-corrected baseline",
    "pressure_absolute":  "Absolute pressure + trend",
    "pressure_long_window": "12h pressure window",
    "pressure_lagged":    "Pressure lagged by 6h",
    "pressure_combined":  "Combined pressure signals",
}


def _strip_tags(html: str) -> str:
    """Remove HTML tags for plain-text regex matching."""
    return re.sub(r'<[^>]+>', '', html)


def _extract_report_meta(html: str) -> dict[str, str | None]:
    """Parse current/index.html for date and best model info."""
    text = _strip_tags(html)

    # Title: "Daily Model Analysis — YYYY-MM-DD" or "<h1>…"
    meta: dict[str, str | None] = {"date": None, "best_model": None, "best_f1": None}

    m = re.search(r'Daily Model Analysis[^—]*[—–-]\s*(\d{4}-\d{2}-\d{2})', text)
    if m:
        meta["date"] = m.group(1)

    # Best model from the "Best overall (F-beta=N): model @ T%" line
    m = re.search(r'Best overall[^:]*:\s*([\w_]+)', text)
    if m:
        meta["best_model"] = m.group(1)
        # Extract F1 from leaderboard table: <td>model_name</td><td>X.XXX</td>
        f1_m = re.search(
            rf'{re.escape(m.group(1))}</td>\s*<td>([0-9.]+)', html
        )
        if f1_m:
            meta["best_f1"] = f1_m.group(1)

    return meta


def _detect_models(html: str) -> list[str]:
    """Find which models appear in the leaderboard table."""
    text = _strip_tags(html)
    models = []
    for model_id in MODEL_DESCRIPTIONS:
        if re.search(rf'^{model_id}\s', text, re.MULTILINE):
            models.append(model_id)
    return models


def main():
    current_html = Path("current/index.html")
    if not current_html.exists():
        print("❌ current/index.html not found — skipping landing page")
        return

    html_content = current_html.read_text()
    meta = _extract_report_meta(html_content)

    date = meta["date"] or datetime.utcnow().strftime("%Y-%m-%d")
    best_model = meta["best_model"] or "N/A"
    best_f1 = meta["best_f1"]

    # Model list (only models that exist in the report)
    models_in_report = _detect_models(html_content)
    if not models_in_report:
        models_in_report = list(MODEL_DESCRIPTIONS.keys())

    model_items = "\n".join(
        f'                <li><strong>{m}</strong> — {MODEL_DESCRIPTIONS.get(m, "")}</li>'
        for m in models_in_report
    )

    best_str = f"{best_model} (F1: {best_f1})" if best_f1 else best_model

    landing = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rain Analysis — Model Performance Reports</title>
    <link rel="stylesheet" href="assets/style.css">
</head>
<body>
    <header>
        <h1>🌧️ Rain Prediction Model Analysis</h1>
        <p>Automated performance tracking and reports</p>
    </header>

    <nav>
        <a href="index.html" class="active">Home</a>
        <a href="current/index.html">Latest Report</a>
        <a href="history/index.html">History</a>
        <a href="metrics/index.html">Metrics Timeline</a>
    </nav>

    <main>
        <section class="intro">
            <h2>About This Project</h2>
            <p>This site tracks the performance of multiple rain prediction models, comparing their accuracy against real precipitation data from multiple sources.</p>

            <h3>Current Models</h3>
            <ul>
{model_items}
            </ul>
        </section>

        <section class="latest">
            <h2>Latest Results</h2>
            <div class="report-card">
                <h3>Daily Report — {date}</h3>
                <p>Best model: <strong>{best_str}</strong></p>
                <a href="current/index.html" class="btn">View Full Report →</a>
            </div>
        </section>

        <section class="quick-links">
            <h2>Quick Links</h2>
            <div class="cards">
                <div class="card">
                    <h3>📊 Current Performance</h3>
                    <p>Latest model metrics and comparisons</p>
                    <a href="current/index.html">View →</a>
                </div>
                <div class="card">
                    <h3>📅 Historical Reports</h3>
                    <p>Browse past analysis results</p>
                    <a href="history/index.html">Browse →</a>
                </div>
                <div class="card">
                    <h3>📈 Metrics Timeline</h3>
                    <p>Track performance trends over time</p>
                    <a href="metrics/index.html">Explore →</a>
                </div>
            </div>
        </section>
    </main>

    <footer>
        <p>Auto-generated from <a href="https://github.com/Kickoman/rain-analysis">rain-analysis</a> repository</p>
        <p>Last updated: <span id="last-update">{date}</span></p>
    </footer>
</body>
</html>'''

    Path("index.html").write_text(landing)
    print(f"✅ Generated landing page — {date}, best: {best_str}")


if __name__ == '__main__':
    main()
