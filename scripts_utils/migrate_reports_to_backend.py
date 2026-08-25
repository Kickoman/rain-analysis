#!/usr/bin/env python3
"""
migrate_reports_to_backend.py — Push existing markdown reports to the backend.
==============================================================================

One-off (but idempotent and re-runnable) migration of ``reports/20*.md`` into
the backend's reports API (Phase 4, #400). Structure is extracted with the
shared ``report_parse`` module — the single parser rule from #232 — and the
raw markdown rides along in ``meta.source_markdown`` so the migration is
reversible.

Sections that fail to parse are stored as raw text blocks rather than
dropped; ``predictions``/``weather_summary``/``charts_data`` are not
populated for migrated reports (#232).

Usage:
  RAIN_BACKEND_KEY=ra_live_... python migrate_reports_to_backend.py \
      --backend-url http://localhost:8000 [--reports-dir reports] [--dry-run]
"""

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))

import report_parse as rp

# Flat YYYY-MM-DD.md daily reports only — not pressure_variants_*, not the
# timestamped run directories.
REPORT_GLOB = "20??-??-??.md"


def build_content(md: str) -> dict:
    """Structured content per the #232 schema, tolerant of missing sections."""
    plain = md.replace("**", "")

    content: dict = {}

    exec_body = rp.markdown_section(md, r"Executive Summary")
    exec_entry = {}
    if exec_body:
        exec_entry["text"] = exec_body
    best = rp.extract_best_model(plain)
    if best:
        exec_entry["best_model"] = best
    if exec_entry:
        content["executive_summary"] = exec_entry

    data_body = rp.markdown_section(md, r"Data Context")
    if data_body:
        content["data_context"] = {"text": data_body}

    leaderboard = rp.extract_leaderboard_md(md)
    if leaderboard:
        content["models"] = [
            {
                "name": row["model"],
                "metrics": {
                    "f1": row["f1"],
                    "precision": row["precision"],
                    "recall": row["recall"],
                },
                "status": row.get("status"),
            }
            for row in leaderboard
        ]

    mw_body = rp.markdown_section(md, r"Multi-Window Comparison")
    if mw_body:
        entry = {"text": mw_body}
        tables = {
            title: rp.parse_markdown_table(sub_body)
            for title, sub_body in rp.markdown_subsections(mw_body)
            if rp.parse_markdown_table(sub_body)
        }
        if tables:
            entry["tables"] = tables
        content["multi_window_comparison"] = entry

    rank_body = rp.markdown_section(md, r"Model Rankings")
    if rank_body:
        content["rankings"] = {"text": rank_body}

    temporal_body = rp.markdown_section(md, r"Temporal Metrics")
    if temporal_body:
        entry = {"text": temporal_body}
        rows = rp.parse_markdown_table(temporal_body)
        if rows:
            entry["rows"] = rows
        content["temporal_metrics"] = entry

    precip_body = rp.markdown_section(md, r"Precipitation Source Reliability")
    if precip_body:
        entry = {"text": precip_body}
        rows = rp.parse_markdown_table(precip_body)
        if rows:
            entry["rows"] = rows
        content["precipitation_source_reliability"] = entry

    return content


def report_date_of(path: str, md: str) -> str | None:
    """Date from the title, cross-checked against the filename."""
    from_title = rp.extract_date(md)
    from_name = re.match(r"(\d{4}-\d{2}-\d{2})\.md$", os.path.basename(path))
    filename_date = from_name.group(1) if from_name else None
    if from_title and filename_date and from_title != filename_date:
        print(f"[WARN] {path}: title date {from_title} != filename {filename_date}; "
              f"using filename", file=sys.stderr)
        return filename_date
    return from_title or filename_date


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--backend-url", required=True)
    parser.add_argument("--api-key", default=os.environ.get("RAIN_BACKEND_KEY"))
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and report, POST nothing")
    args = parser.parse_args()

    if not args.dry_run and not args.api_key:
        print("[ERROR] No API key: pass --api-key or set RAIN_BACKEND_KEY", file=sys.stderr)
        return 1

    paths = sorted(glob.glob(os.path.join(args.reports_dir, REPORT_GLOB)))
    if not paths:
        print(f"[ERROR] No reports matching {REPORT_GLOB} in {args.reports_dir}", file=sys.stderr)
        return 1

    endpoint = args.backend_url.rstrip("/") + "/api/v1/reports"
    session = requests.Session()
    ok = failed = 0

    for path in paths:
        md = open(path, encoding="utf-8").read()
        report_date = report_date_of(path, md)
        if not report_date:
            print(f"[ERROR] {path}: no report date found", file=sys.stderr)
            failed += 1
            continue

        content = build_content(md)
        sections = sorted(content.keys())
        models_n = len(content.get("models", []))
        if args.dry_run:
            print(f"[DRY] {report_date}: {models_n} models, sections: {', '.join(sections)}")
            ok += 1
            continue

        payload = {
            "report_date": report_date,
            "content": content,
            "meta": {
                "source_markdown": md,
                "migrated_from": path,
                "parser": "report_parse.md",
            },
        }
        response = session.post(
            endpoint,
            json=payload,
            headers={"X-API-Key": args.api_key},
            timeout=60,
        )
        if response.status_code == 200:
            action = response.json().get("action")
            print(f"[OK] {report_date}: {action} ({models_n} models)")
            ok += 1
        else:
            print(f"[ERROR] {report_date}: HTTP {response.status_code}: "
                  f"{response.text[:200]}", file=sys.stderr)
            failed += 1

    print(f"[DONE] {ok} migrated, {failed} failed", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
