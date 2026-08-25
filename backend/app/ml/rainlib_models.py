"""Adapter that serves rainlib formula models through the sklearn interface.

The analysis side defines its models as plain functions over a ModelContext
(see analysis/rainlib.py); the backend serves models through objects with a
``predict_proba(features_df)`` method. This adapter bridges the two so an
MLModel row with ``config["kind"] == "rainlib"`` runs the shared rainlib
code directly — no pickling of closures, no drift between analysis and
serving (the reason the rainlib/ shim package exists).
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# rainlib is a repo-root package (a shim over analysis/rainlib.py); the
# backend runs from backend/, so put the repo root on the path first.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from rainlib import MODELS as RAINLIB_MODELS, ModelContext, derivative  # noqa: E402

# ModelContext fields an adapter can feed from feature columns
_CONTEXT_FIELDS = ("spread", "spread_deriv", "pressure", "temp", "abs_humidity", "ha_spread_trend")


class RainlibModelAdapter:
    """Wrap one rainlib model function as a predict_proba-style estimator.

    Expects a features DataFrame with a DatetimeIndex and columns named
    after ModelContext fields (spread, pressure, ...). ``spread_deriv`` is
    computed from ``spread`` when absent. Output is the model's 0-100
    probability rescaled to 0-1.
    """

    def __init__(self, rainlib_model: str, derivative_window: str = "3h"):
        if rainlib_model not in RAINLIB_MODELS:
            raise ValueError(
                f"Unknown rainlib model {rainlib_model!r}; "
                f"available: {sorted(RAINLIB_MODELS)}"
            )
        self.rainlib_model = rainlib_model
        self.derivative_window = derivative_window

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        if "spread" not in features.columns:
            raise ValueError("rainlib models require a 'spread' feature column")
        if not isinstance(features.index, pd.DatetimeIndex):
            raise ValueError("rainlib models require a DatetimeIndex on the features frame")

        kwargs = {}
        for field in _CONTEXT_FIELDS:
            if field in features.columns:
                kwargs[field] = features[field]
        if "spread_deriv" not in kwargs:
            # Leading rows have no window to differentiate over; "no trend
            # information" is 0, not NaN, for serving purposes.
            kwargs["spread_deriv"] = derivative(
                features["spread"], window=self.derivative_window
            ).fillna(0.0)
        else:
            kwargs["spread_deriv"] = kwargs["spread_deriv"].fillna(0.0)

        ctx = ModelContext(**kwargs)
        percent = RAINLIB_MODELS[self.rainlib_model](ctx)
        return (
            pd.Series(percent).reindex(features.index).to_numpy(dtype=float) / 100.0
        )


def get_rainlib_adapter(config: dict) -> RainlibModelAdapter:
    """Build an adapter from an MLModel.config with kind == "rainlib"."""
    name = config.get("rainlib_model")
    if not name:
        raise ValueError('config["rainlib_model"] is required for kind "rainlib"')
    return RainlibModelAdapter(
        name, derivative_window=config.get("derivative_window", "3h")
    )
