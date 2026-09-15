#!/usr/bin/env python3
"""
trim_forecast.py — drop the forecast tail from an Open-Meteo past-days fetch.
=============================================================================

The forecast endpoint answers with the past days *and* the days ahead. Those
future hours are a model's guess, not an observation, and letting them into
the archive means scoring rain models against tomorrow's forecast — which
inflates every score, since the same physics produced both.

Keeps hours up to and including the most recent completed hour, writes the
same JSON shape back out.

Usage:
  python trim_forecast.py fetched.json data/archive/om_backfill_forecast.json
"""

import json
import sys
from datetime import datetime, timezone


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    src, dst = sys.argv[1], sys.argv[2]

    with open(src) as f:
        payload = json.load(f)
    hourly = payload.get("hourly")
    if not hourly or "time" not in hourly:
        print(f"[ERROR] {src}: no hourly.time block", file=sys.stderr)
        return 1

    cutoff = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    cutoff_s = cutoff.strftime("%Y-%m-%dT%H:%M")
    keep = [i for i, t in enumerate(hourly["time"]) if t <= cutoff_s]
    if not keep:
        print(f"[ERROR] {src}: nothing at or before {cutoff_s}", file=sys.stderr)
        return 1

    # Capture the original length first: trimming "time" in place would change
    # it mid-loop and leave every other series untrimmed and misaligned.
    n = len(hourly["time"])
    for key, values in list(hourly.items()):
        if isinstance(values, list) and len(values) == n:
            hourly[key] = [values[i] for i in keep]

    with open(dst, "w") as f:
        json.dump(payload, f)
    print(f"[DONE] {hourly['time'][0]} → {hourly['time'][-1]} "
          f"({len(keep)} hours) → {dst}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
