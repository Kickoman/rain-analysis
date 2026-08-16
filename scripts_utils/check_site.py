#!/usr/bin/env python3
"""
check_site.py — refuse to publish a site that lost content.
===========================================================

The deploy regenerates the whole site on every run and pushes the result with an
unconditional ``git add .``. That makes every generator failure look identical to
a successful run: the job stays green and whatever happened to be on disk goes
live. Several incidents came from exactly this — a parser that quietly returned
no rows dropped a model from every page, and the build reported success.

This is the gate that turns those into a red build. It compares the freshly
generated tree against the currently published one (the gh-pages ``HEAD``) and
fails when the site would shrink: fewer history cards, fewer dates in the metrics
series, a page that vanished or collapsed to a stub.

Growth is always fine. Only loss is suspicious, and loss is what silent breakage
looks like.

Usage (from the gh-pages working tree, after the generators have run):
    python3 scripts_utils/check_site.py --baseline-ref HEAD
    python3 scripts_utils/check_site.py --no-baseline     # first-ever publish
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# Pages the site cannot be published without, and the smallest size that is
# plausibly a real page rather than an empty shell.
REQUIRED_PAGES = {
    "index.html": 1000,
    "current/index.html": 1000,
    "history/index.html": 1000,
    "metrics/index.html": 1000,
    "metrics/data.json": 200,
}

CARD_RE = re.compile(r'<div class="card">', re.IGNORECASE)


class CheckFailed(Exception):
    """A condition that must block publication."""


def read_baseline(ref: str, path: str) -> str | None:
    """Content of ``path`` at ``ref``, or None when it did not exist there."""
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        capture_output=True, text=True,
    )
    return result.stdout if result.returncode == 0 else None


def check_required_pages(root: Path) -> list[str]:
    problems = []
    for rel, min_bytes in REQUIRED_PAGES.items():
        path = root / rel
        if not path.exists():
            problems.append(f"{rel}: missing")
            continue
        size = path.stat().st_size
        if size < min_bytes:
            problems.append(f"{rel}: only {size} bytes (expected at least {min_bytes})")
    return problems


def count_cards(html: str) -> int:
    return len(CARD_RE.findall(html))


def check_history(root: Path, baseline: str | None) -> list[str]:
    current = (root / "history/index.html").read_text(encoding="utf-8")
    now = count_cards(current)
    if now == 0:
        return ["history/index.html: no report cards"]
    if baseline is None:
        return []
    before = count_cards(baseline)
    if now < before:
        return [f"history/index.html: {before} cards published, {now} now — reports were lost"]
    return []


def check_metrics(root: Path, baseline: str | None,
                  allowed_drops: set[str] | None = None) -> list[str]:
    raw = (root / "metrics/data.json").read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return [f"metrics/data.json: not valid JSON ({e})"]

    problems = []
    dates = data.get("dates") or []
    models = data.get("models") or {}
    if not dates:
        problems.append("metrics/data.json: no dates")
    if not models:
        problems.append("metrics/data.json: no models")

    if baseline is None:
        return problems

    try:
        before = json.loads(baseline)
    except json.JSONDecodeError:
        return problems  # published copy is unreadable; nothing to compare against

    old_dates = set(before.get("dates") or [])
    lost_dates = old_dates - set(dates)
    if lost_dates:
        problems.append(
            f"metrics/data.json: {len(lost_dates)} date(s) dropped, e.g. "
            f"{', '.join(sorted(lost_dates)[:3])}")

    # A model disappearing entirely is the ha_live_actual failure mode: its rows
    # became N/A, three parsers read that as "no match", and it silently left the
    # site. A model present with null values is fine and is not flagged here.
    # A drop can be legitimate — the 2026-08-15 backfill superseded the reports
    # that carried the pre-rename `ha_live` series — but only when named
    # explicitly via --allow-drop, so intent is recorded in the workflow diff.
    lost_models = set(before.get("models") or {}) - set(models)
    acknowledged = lost_models & (allowed_drops or set())
    for name in sorted(acknowledged):
        print(f"   ⚠ metrics/data.json: model dropped as allowed: {name}",
              file=sys.stderr)
    lost_models -= acknowledged
    if lost_models:
        problems.append(
            f"metrics/data.json: model(s) dropped: {', '.join(sorted(lost_models))}")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--root", default=".", help="Site root (default: cwd)")
    parser.add_argument("--baseline-ref", default="HEAD",
                        help="Git ref holding the currently published site (default: HEAD)")
    parser.add_argument("--no-baseline", action="store_true",
                        help="Skip comparisons — only check the tree is complete")
    parser.add_argument("--allow-drop", action="append", default=[],
                        metavar="MODEL",
                        help="Model name whose disappearance from "
                             "metrics/data.json is intentional (repeatable)")
    args = parser.parse_args()

    root = Path(args.root)
    problems = check_required_pages(root)
    if problems:
        # Without the pages themselves there is nothing to compare.
        for p in problems:
            print(f"   ✗ {p}", file=sys.stderr)
        print("\n❌ Site is incomplete — refusing to publish", file=sys.stderr)
        return 1

    def baseline_for(path: str) -> str | None:
        return None if args.no_baseline else read_baseline(args.baseline_ref, path)

    problems += check_history(root, baseline_for("history/index.html"))
    problems += check_metrics(root, baseline_for("metrics/data.json"),
                              allowed_drops=set(args.allow_drop))

    if problems:
        for p in problems:
            print(f"   ✗ {p}", file=sys.stderr)
        print("\n❌ Site would lose content — refusing to publish", file=sys.stderr)
        return 1

    cards = count_cards((root / "history/index.html").read_text(encoding="utf-8"))
    data = json.loads((root / "metrics/data.json").read_text(encoding="utf-8"))
    print(f"✅ Site checks passed — {cards} history cards, "
          f"{len(data.get('dates', []))} dates, {len(data.get('models', {}))} models")
    return 0


if __name__ == "__main__":
    sys.exit(main())
