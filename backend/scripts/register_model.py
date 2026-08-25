#!/usr/bin/env python3
"""
Register or update an MLModel row so the models table is not hand-edited.

Examples:
  # rainlib formula model served straight from shared code
  python scripts/register_model.py onset_gate --kind rainlib \
      --rainlib-model onset_gate --threshold 0.5 \
      --sensor-map spread=sensor.outside_dew_point_spread \
                   ha_spread_trend=sensor.outside_dew_point_spread_trend \
                   pressure=sensor.filtered_pressure

  # fitted sklearn model persisted as a pickle in backend/models/
  python scripts/register_model.py logistic_v2 --kind sklearn \
      --file-path logistic_v2.pkl --threshold 0.35 \
      --features spread spread_deriv pressure \
      --sensor-map spread=sensor.outside_dew_point_spread \
                   pressure=sensor.filtered_pressure
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.ml import MLModel


def parse_sensor_map(pairs: list[str]) -> dict:
    mapping = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--sensor-map entries must be feature=sensor, got {pair!r}")
        feature, sensor = pair.split("=", 1)
        mapping[feature] = sensor
    return mapping


async def register(args) -> int:
    config = {
        "kind": args.kind,
        "threshold": args.threshold,
    }
    if args.kind == "rainlib":
        if not args.rainlib_model:
            raise SystemExit("--rainlib-model is required for kind rainlib")
        config["rainlib_model"] = args.rainlib_model
    if args.file_path:
        config["file_path"] = args.file_path
    if args.features:
        config["features"] = args.features
    if args.sensor_map:
        config["sensor_map"] = parse_sensor_map(args.sensor_map)

    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(select(MLModel).where(MLModel.name == args.name))
        ).scalar_one_or_none()

        if existing is None:
            model = MLModel(
                name=args.name,
                version=args.version,
                description=args.description,
                config=config,
                active=not args.inactive,
            )
            db.add(model)
            action = "registered"
        else:
            existing.version = args.version
            existing.description = args.description or existing.description
            existing.config = config
            existing.active = not args.inactive
            model = existing
            action = "updated"

        await db.commit()
        await db.refresh(model)
        print(f"Model '{model.name}' {action}: id={model.id} version={model.version} "
              f"active={model.active}")
        print(f"  config: {model.config}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[1],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("name", help="Unique model name")
    parser.add_argument("--version", default="1", help="Model version label")
    parser.add_argument("--description", default=None)
    parser.add_argument("--kind", choices=["sklearn", "rainlib"], default="sklearn")
    parser.add_argument("--rainlib-model", help="rainlib MODELS key (kind rainlib)")
    parser.add_argument("--file-path", help="Pickle path, relative to models_dir (kind sklearn)")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--features", nargs="+", help="Ordered feature list the estimator expects")
    parser.add_argument("--sensor-map", nargs="+", metavar="feature=sensor",
                        help="Which stored sensor feeds each feature")
    parser.add_argument("--inactive", action="store_true", help="Register without activating")

    return asyncio.run(register(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
