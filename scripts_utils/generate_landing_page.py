#!/usr/bin/env python3
"""Generate root index.html (landing page) from the latest daily report.

Reads current/index.html, extracts the best model + date, and produces
a landing page with up-to-date model descriptions and latest results.
"""

import html as html_mod
import sys
from pathlib import Path
import re
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_parse import (  # noqa: E402
    extract_best_model,
    extract_date,
    extract_leaderboard,
    extract_onset_date,
    extract_onset_scoreboard,
    extract_onset_window,
    extract_recommended,
    is_onset_report,
    strip_tags,
)
from glyphs import to_ascii  # noqa: E402
from page_shell import (  # noqa: E402
    REPO_URL,
    SUBTITLE_REPORTS,
    render_page,
)


# Single source of truth for model descriptions.
#
# Deliberately carries no F1 values: these are static constants, and the numbers
# that used to live here were pre-2026-08-13 figures the changelog has since
# declared superseded — the homepage showed `tuned` at 0.441 here and 0.273 in
# the live table three sections below. The ✅/❌ prefixes stay; _is_failed_experiment
# depends on them.
MODEL_DESCRIPTIONS = {
    "original":           "Baseline v0.1 — dew-point spread + trend",
    "tuned":              "Grid-search optimized parameters",
    "trend_dominant":     "❌ Failed experiment — trend-primary",
    "ha_live_actual":     "✅ Production — actual HA sensor",
    "ha_live_replica":   "🔄 Replica backtest of production formula",
    "ha_live":            "✅ Production — deployed in Home Assistant — legacy",
    "pressure_aware":     "Pressure-corrected baseline",
    "pressure_absolute":  "Absolute pressure + trend",
    "pressure_long_window": "12h pressure window",
    "pressure_lagged":    "Pressure lagged by 6h",
    "pressure_combined":  "Combined pressure signals",
    "combined":           "✅ Fully combined — temp + humidity + pressure signals",
}


_strip_tags = strip_tags


# The documentation the landing page offers, in the order it offers it, with a
# blurb written here rather than scraped from the document. Cards are emitted
# only for pages that exist under ``docs/`` when the landing page is built —
# the workflow renders documentation before it reaches this generator, so a
# card can never point at a page that was not produced. A document added to
# ``docs_site/`` without an entry here simply does not get a card, which is a
# quieter failure than a 404 on the front page.
DOC_CARDS: tuple[tuple[str, str], ...] = (
    ("GLOSSARY", "What onset, catches, lift and AUC mean here."),
    ("MODELS", "Every candidate and the parameters behind it."),
    ("ALERT_RULE", "The rule the deployed sensor actually runs."),
    ("BASELINE_MODEL", "The production model, in detail."),
    ("DATA_SOURCES", "Where ground truth comes from, and how it fails."),
    ("CHANGELOG", "What changed in the pipeline, and which results it invalidated."),
    ("CLI_RUNNER", "Running the analysis yourself."),
    ("HA_DATA_FETCHER", "Pulling sensor history out of Home Assistant."),
    ("daily_analysis_output_format", "The shape of a daily report."),
)

CONTRIBUTING_URL = f"{REPO_URL}/blob/master/CONTRIBUTING.md"


def _card(title: str, blurb: str, href: str, label: str) -> str:
    """One card. ``<div class="card">`` is spelled literally on purpose.

    ``check_site.CARD_RE`` counts that exact string to decide whether a deploy
    has lost content, so it is a published interface, not formatting.
    """
    return (f'                <div class="card">\n'
            f'                    <h3>{title}</h3>\n'
            f'                    <p>{blurb}</p>\n'
            f'                    <a href="{href}">&gt; {label}</a>\n'
            f'                </div>')


def _doc_cards(root: Path | None = None) -> str:
    """Cards for the documentation pages that were actually generated."""
    docs = (root or Path(".")) / "docs"
    cards = [
        _card(stem.replace("_", " ").lower(), blurb, f"docs/{stem}.html", "read")
        for stem, blurb in DOC_CARDS
        if (docs / f"{stem}.html").exists()
    ]
    # Contributing lives on GitHub, not on the site, so it is always available.
    cards.append(_card("contributing", "Development workflow, on GitHub.",
                       CONTRIBUTING_URL, "read"))
    return "\n".join(cards)


def _reports_published(root: Path | None = None) -> int | None:
    """How many report pages history holds, or ``None`` if it has not been built."""
    history = (root or Path(".")) / "history"
    if not history.is_dir():
        return None
    return sum(1 for f in history.glob("*.html") if f.name != "index.html")


def _status_block(rows: list[tuple[str, str]]) -> str:
    """The terminal panel: a fake command and its aligned output.

    Alignment is computed rather than hand-spaced, so a longer label later
    cannot quietly break the column. ``<pre>`` is the design's machine surface —
    green on black — and it is the only place on the page where the site speaks
    in the pipeline's voice rather than in prose.
    """
    width = max(len(label) for label, _ in rows)
    body = "\n".join(f"{label.ljust(width)}  {html_mod.escape(value)}"
                      for label, value in rows)
    return f"<pre>$ rain-analysis status\n{body}</pre>"


def _is_failed_experiment(model_name: str) -> bool:
    """Check if a model is marked as a failed experiment in MODEL_DESCRIPTIONS.
    
    Returns True if the model's description starts with ❌, indicating
    it's a known failed experiment that should not be considered a valid "best model".
    """
    desc = MODEL_DESCRIPTIONS.get(model_name, "")
    return desc.startswith("❌")


def _extract_onset_meta(html: str) -> dict:
    """Headline facts from an onset-format report.

    The landing page used to lead with "best model by F1", a nowcast score:
    the model best at noticing rain that is already falling. That is the one
    thing the alert cannot use, so the hero now carries the onset verdict —
    what warns before rain starts, how often, and at what cost — or says
    plainly that nothing does.
    """
    text = _strip_tags(html)
    window = extract_onset_window(html)
    rows = extract_onset_scoreboard(html)
    recommended = extract_recommended(text)
    proven = [r for r in rows if r.get("verdict") == "works"]
    deployed = next((r for r in rows if r["model"] == "ha_live_actual"), None)
    return {
        "date": extract_onset_date(html),
        "onset_format": True,
        "rows": rows,
        "recommended": recommended,
        "proven": proven,
        "deployed": deployed,
        "window_days": window.get("window_days"),
        "onsets": window.get("onsets"),
        "onsets_cross_label": window.get("onsets_cross_label"),
    }


def _extract_report_meta(html: str) -> dict[str, str | None]:
    """Parse current/index.html for date and best model info."""
    text = _strip_tags(html)

    meta: dict[str, str | None] = {"date": None, "best_model": None, "best_f1": None, "om_coverage": None}
    meta["date"] = extract_date(text)

    model = extract_best_model(text)
    if model:
        meta["best_model"] = model
        # Read the metric from the located leaderboard, matching the model name
        # as a whole cell. The previous unanchored search matched "combined"
        # inside "pressure_combined</td>" and, on an N/A row, walked forward into
        # the Temporal Metrics table and reported its score instead.
        for row in extract_leaderboard(html):
            if row["model"] == model:
                meta["best_f1"] = None if row["f1"] is None else f"{row['f1']:.3f}"
                break

    # Extract Open-Meteo coverage (issue #342)
    cov_m = re.search(r'Open-Meteo precipitation:\s*([0-9.]+)%', text)
    if cov_m:
        meta["om_coverage"] = float(cov_m.group(1))

    return meta


def _detect_models(html: str) -> list[dict]:
    """Models named in the leaderboard, each with its F1 (``None`` when N/A).

    Models whose metrics are all ``N/A`` are kept rather than dropped: the
    production model `ha_live_actual` reports N/A whenever the analysis window
    reaches past the Home Assistant recorder's retention, and silently removing
    it from the homepage hides that instead of explaining it.
    """
    return [{"model": r["model"], "f1": r["f1"]} for r in extract_leaderboard(html)]


def build_onset_landing(html_content: str) -> None:
    """Landing page for the onset-first report format.

    One hero fact, one table, and the honest caveat. The old page listed
    fifteen models with nowcast F1 next to each; that list answered "which
    model notices rain best" for a product whose entire job is to speak before
    the rain, so it is gone.
    """
    meta = _extract_onset_meta(html_content)
    date = meta["date"] or datetime.utcnow().strftime("%Y-%m-%d")
    proven, deployed = meta["proven"], meta["deployed"]
    rec = meta["recommended"]

    def num(value, digits=2, dash="—"):
        return dash if value is None else f"{value:.{digits}f}"

    if proven:
        best = max(proven, key=lambda r: r.get("lift") or 0)
        thr = f" at {rec['threshold']:.0f}%" if rec and rec["model"] == best["model"] else ""
        # Any of these can be absent on a window where the candidate had no
        # usable operating point; a missing number must read as a dash, not
        # crash the generator and take the whole landing page down with it.
        share = (f" ({best['caught'] / best['onsets'] * 100:.0f}%)"
                 if best.get("caught") is not None and best.get("onsets") else "")
        headline = (
            f"<strong><code>{best['model']}</code>{thr}</strong> warns before "
            f"{best.get('caught', '—')} of {best.get('onsets', '—')} rain starts"
            f"{share}, costing {num(best.get('alert_hours_per_week'), 0)} "
            f"alert-hours a week — {num(best.get('lift'))}× better than "
            "alerting at random."
        )
    elif not any(r.get("verdict") in {"works", "ranks_only", "one_label_only", "chance"}
                 for r in meta["rows"]):
        # Distinct from "measured and nothing won": the record simply does not
        # hold enough rain starts yet, and saying otherwise on the front page
        # would be a stronger claim than the report itself makes.
        headline = (f"<strong>Not enough rain starts yet.</strong> The record holds "
                    f"{meta['onsets'] or '—'} of them; below fifteen the confidence "
                    "intervals are wider than any difference between candidates, so "
                    "nothing is named.")
    else:
        headline = ("<strong>Nothing currently beats a coin toss.</strong> No candidate's "
                    "confidence interval clears chance on both yardsticks.")

    if deployed and deployed.get("roc_auc") is None:
        deployed_line = ("The deployed sensor <code>ha_live_actual</code> had no usable "
                         "history in this window and could not be scored.")
    elif deployed and deployed.get("verdict") != "works":
        deployed_line = (
            f"The sensor actually deployed in Home Assistant, <code>ha_live_actual</code>, "
            f"scores {num(deployed.get('roc_auc'))} — chance is 0.50. It reaches "
            f"{deployed.get('caught', '—')} of {deployed.get('onsets', '—')} starts, which is what "
            f"{num(deployed.get('alert_hours_per_week'), 0)} alert-hours a week reach by luck."
        )
    elif deployed:
        deployed_line = (f"The deployed sensor <code>ha_live_actual</code> clears chance "
                         f"({num(deployed.get('roc_auc'))}).")
    else:
        deployed_line = "The deployed sensor had no data in this window."

    # ASCII, not emoji: the published page carries "[ok]" where the report's
    # markdown carries "✅". `report_parse._VERDICT_MARK` reads both, so the
    # already-published pages on gh-pages keep parsing.
    marks = {"works": "[ok]", "ranks_only": "[~]", "one_label_only": "[!]", "chance": "—"}

    def row_html(r: dict) -> str:
        lift = "—" if r.get("lift") is None else f"{r['lift']:.2f}"
        hours = "—" if r.get("alert_hours_per_week") is None else f"{r['alert_hours_per_week']:.0f}"
        auc = "—" if r.get("roc_auc") is None else f"{r['roc_auc']:.2f}"
        ci = r.get("roc_auc_ci") or [None, None]
        ci_txt = f" ({ci[0]:.2f}–{ci[1]:.2f})" if ci[0] is not None else ""
        return (f"                    <tr><td><code>{r['model']}</code></td>"
                f"<td>{r['caught']}/{r['onsets']}</td><td>{lift}</td>"
                f"<td>{hours}</td><td>{auc}{ci_txt}</td>"
                f"<td>{marks.get(r.get('verdict'), '—')}</td></tr>")

    top = sorted(meta["rows"], key=lambda r: -(r.get("roc_auc") or 0))[:6]
    table_rows = "\n".join(row_html(r) for r in top)

    # --- the terminal panel ------------------------------------------------
    days = meta["window_days"]
    record = f"{days:.0f} days" if days else "unknown length"
    if meta["onsets"] is not None:
        cross = meta.get("onsets_cross_label")
        record += f"   onsets {meta['onsets']} (open-meteo)"
        record += f" / {cross} (cross-label)" if cross is not None else ""

    if rec:
        recommended = f"{rec['model']} @ {rec['threshold']:.0f}%"
        named = next((r for r in meta["rows"] if r["model"] == rec["model"]), None)
        if named and named.get("caught") is not None and named.get("onsets"):
            recommended += f"   catches {named['caught']}/{named['onsets']}"
        if named and named.get("lift") is not None:
            recommended += f"   lift {named['lift']:.2f}"
    else:
        recommended = "nothing clears chance"

    if deployed and deployed.get("roc_auc") is not None:
        verdict = " (chance)" if deployed.get("verdict") != "works" else ""
        sensor = f"ha_live_actual   auc {deployed['roc_auc']:.2f}{verdict}"
    else:
        sensor = "ha_live_actual   no usable history in this window"

    prose_record = re.sub(r"\s{2,}", ", ", record).replace("onsets", "holding")

    status_rows = [("report", date), ("record", record)]
    published = _reports_published()
    if published is not None:
        status_rows.append(("reports published", str(published)))
    status_rows += [("recommended", recommended), ("deployed sensor", sensor)]

    body = f'''        <section class="intro">
            <h1>does anything warn before rain?</h1>
            <p>One question, measured every day: do the sensors in this house say
            anything before the first drop? Nothing on this page is written by
            hand — every number below comes out of the daily analysis.</p>

{_status_block(status_rows)}
        </section>

        <section class="latest">
            <h2>where it stands — {date}</h2>
            <div class="report-card">
                <p>{headline}</p>
                <p>{deployed_line}</p>
                <a href="current/index.html" class="btn">read the full report</a>
            </div>
        </section>

        <section class="intro">
            <h2>top candidates</h2>
            <p>Scored over {prose_record} rain starts.
            <strong>Catches</strong> counts starts with an alert in the three hours before them;
            <strong>lift</strong> divides that by what the same alert time would catch at random,
            so 1.0 means the alerts carry no information. <code>[ok]</code> marks a candidate that
            clears chance on two independent yardsticks <em>and</em> beats random at its own threshold.</p>
            <div class="table-wrap">
            <table>
                <thead><tr><th>candidate</th><th>catches</th><th>lift</th>
                <th>alert h/wk</th><th>front auc (95% ci)</th><th></th></tr></thead>
                <tbody>
{table_rows}
                </tbody>
            </table>
            </div>
        </section>

        <section class="quick-links">
            <h2>where to look</h2>
            <div class="cards">
{_card("over time", "Has the skill held up, day by day?", "metrics/index.html", "explore")}
{_card("past reports", "Every daily report, newest first. Nothing is ever removed.", "history/index.html", "browse")}
{_card("latest report", "The full analysis behind the verdict above.", "current/index.html", "view")}
            </div>
        </section>

        <section class="documentation">
            <h2>documentation</h2>
            <div class="cards">
{_doc_cards()}
            </div>
        </section>'''

    landing = render_page(
        title="Does anything warn before rain?",
        description="Which rain-prediction model warns before rain starts, how "
                    "often it is right, and what the alerts cost.",
        subtitle=SUBTITLE_REPORTS,
        body=to_ascii(body),
        active="home",
        header_extra='        <div id="live-rain-widget"></div>',
        extra_body='    <script src="assets/live-widget.js" defer></script>',
    )

    Path("index.html").write_text(landing)
    print(f"[ok] generated landing page (onset format) — {date}")


def main():
    current_html = Path("current/index.html")
    if not current_html.exists():
        # Exit non-zero. Returning 0 here let the workflow carry on to
        # `git add . && git push`, publishing whatever happened to be on disk
        # while the only sign of trouble was this line in the Actions log.
        print("[x] current/index.html not found — cannot build landing page", file=sys.stderr)
        sys.exit(1)

    html_content = current_html.read_text()

    if is_onset_report(html_content):
        return build_onset_landing(html_content)

    meta = _extract_report_meta(html_content)

    date = meta["date"] or datetime.utcnow().strftime("%Y-%m-%d")
    best_model = meta["best_model"] or "N/A"
    best_f1 = meta["best_f1"]
    om_coverage = meta.get("om_coverage")
    
    # Issue #342: Don't show "best model" if coverage is too low
    LOW_COVERAGE_THRESHOLD = 20.0
    low_coverage = om_coverage is not None and om_coverage < LOW_COVERAGE_THRESHOLD
    
    # Issue #336: Warn if "best model" is a known failed experiment
    failed_experiment = best_model != "N/A" and _is_failed_experiment(best_model)

    # Model list (only models that exist in the report)
    models_in_report = _detect_models(html_content)
    if not models_in_report:
        # Fallback: use known models but mark as stale
        models_in_report = [{"model": m, "f1": None} for m in MODEL_DESCRIPTIONS]
        fallback_note = ' <em>(using fallback model list — table parsing failed)</em>'
    else:
        fallback_note = ''

    def _model_item(entry: dict) -> str:
        name = entry["model"]
        desc = MODEL_DESCRIPTIONS.get(name, "New model — no description yet")
        metric = "⚪ no data this run" if entry["f1"] is None else f"F1={entry['f1']:.3f}"
        return f'                <li><strong>{name}</strong> — {desc} <em>({metric})</em></li>'

    model_items = "\n".join(_model_item(e) for e in models_in_report)

    # Build best model string with warnings
    if low_coverage:
        best_str = f"⚠️ Insufficient data (coverage: {om_coverage:.1f}%)"
    elif failed_experiment:
        # Show the model name/F1 but add a warning that it's a failed experiment
        best_str = f"{best_model} (F1: {best_f1})" if best_f1 else best_model
        best_str += ("<br><small>⚠️ This is a known failed experiment — "
                     "see model descriptions</small>")
    else:
        best_str = f"{best_model} (F1: {best_f1})" if best_f1 else best_model

    body = f'''        <section class="intro">
            <h1>rain prediction model analysis</h1>
            <p>This site tracks several rain-prediction models against real
            precipitation data from more than one source.</p>

            <h2>current models{fallback_note}</h2>
            <ul>
{model_items}
            </ul>
        </section>

        <section class="latest">
            <h2>latest results</h2>
            <div class="report-card">
                <h3>daily report — {date}</h3>
                <p>{"<strong>⚠️ Low ground truth coverage</strong> — model rankings may be unreliable.<br>" if low_coverage else ""}Best model: <strong>{best_str}</strong></p>
                <a href="current/index.html" class="btn">view full report</a>
            </div>
        </section>

        <section class="quick-links">
            <h2>where to look</h2>
            <div class="cards">
{_card("current performance", "Latest model metrics and comparisons.", "current/index.html", "view")}
{_card("historical reports", "Browse past analysis results.", "history/index.html", "browse")}
{_card("metrics timeline", "Track performance trends over time.", "metrics/index.html", "explore")}
            </div>
        </section>

        <section class="documentation">
            <h2>documentation</h2>
            <div class="cards">
{_doc_cards()}
            </div>
        </section>'''

    landing = render_page(
        title="Model Performance Reports",
        description="Automated performance tracking for rain prediction models, "
                    "scored against real precipitation data.",
        subtitle=SUBTITLE_REPORTS,
        body=to_ascii(body),
        active="home",
        header_extra='        <div id="live-rain-widget"></div>',
        extra_body='    <script src="assets/live-widget.js" defer></script>',
    )

    Path("index.html").write_text(landing)
    print(f"[ok] generated landing page — {date}, best: {to_ascii(best_str)}")


if __name__ == '__main__':
    main()
