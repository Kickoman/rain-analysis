"""
learned.py — a fitted rain model, and the harness that makes its scores credible.
=================================================================================

Every model in `rainlib.MODELS` is a hand-weighted blend, and measured over
49,200 hours the best of them ranks at ROC AUC 0.55 while a single raw pressure
reading reaches 0.75. Fitting the weights instead of guessing them is the
obvious next step — but a fitted model is only worth what its validation is
worth, so the harness comes first and the model second.

**Walk-forward, never a random split.** Weather is autocorrelated: an hour drawn
at random has its own neighbours in the training set, so a shuffled split
reports skill the model does not have. `walk_forward()` trains strictly on the
past and scores strictly on the future, the way the model would actually run.

**Logistic regression, not gradient boosting.** On the local archive the two are
indistinguishable (AUC 0.764 vs 0.757), and the linear model gives inspectable
coefficients and probabilities that mean something. A calibrated probability is
what makes a decision threshold meaningful — the fixed 50% cutoff currently
lands at wildly different operating points for each hand-tuned model (45 for
`combined`, 20 for `tuned`, 5 for `ha_live`).

scikit-learn is imported lazily so the rest of the pipeline keeps working in an
environment where it has not been installed yet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:  # pragma: no cover - trivial import plumbing
    from analysis import rainlib as rl
except ImportError:  # pragma: no cover
    import rainlib as rl


# Features the model may use, in the order the measurements ranked them. Cloud
# cover and "it rained last hour" measured higher still, but neither is
# available from the balcony: cloud needs an API, and persistence needs a rain
# sensor the station does not have.
FEATURE_COLUMNS = [
    "pressure",
    "pressure_anomaly",
    "pressure_d3h",
    "pressure_d6h",
    "pressure_d12h",
    "pressure_d24h",
    "spread",
    "spread_min6",
    "spread_d3h",
    "spread_d6h",
    "rh",
    "rh_mean6",
    "abs_hum",
    "abs_hum_d3h",
    "temp",
    "temp_d3h",
    "hour_sin",
    "hour_cos",
    "doy_sin",
    "doy_cos",
]


# 30 days of hourly rows — the row-count equivalent of the "30D" pressure
# baseline, used when the index carries no clock.
BASELINE_ROWS = 24 * 30


def _trailing_slope(series: pd.Series, hours: int) -> pd.Series:
    """Change per hour over a trailing window, as a plain difference.

    `rainlib.derivative` fits a least-squares slope and costs O(n²) — about 20
    seconds per column over the 49,200-hour archive. On a regular grid the
    difference quotient carries the same information at O(n), and these are
    model features rather than a reproduction of a Home Assistant helper, so the
    cheap form is the right one here.
    """
    steps = max(1, int(hours))
    return (series - series.shift(steps)) / steps


def build_features(grid: pd.DataFrame) -> pd.DataFrame:
    """Derive the model's feature frame from an analysis grid.

    Every feature is trailing: a row uses only that hour and earlier ones. That
    is not a stylistic preference — a single centred window would leak the
    future into training and inflate every score that follows.
    """
    features = pd.DataFrame(index=grid.index)

    if "spread" in grid.columns:
        spread = grid["spread"]
    elif {"temp", "rh"} <= set(grid.columns):
        spread = pd.Series(rl.dew_point_spread(grid["temp"], grid["rh"]), index=grid.index)
    else:
        raise ValueError("build_features(): need either 'spread' or both 'temp' and 'rh'")

    features["spread"] = spread
    features["spread_min6"] = spread.rolling(6, min_periods=2).min()
    features["spread_d3h"] = _trailing_slope(spread, 3)
    features["spread_d6h"] = _trailing_slope(spread, 6)

    if "rh" in grid.columns:
        features["rh"] = grid["rh"]
        features["rh_mean6"] = grid["rh"].rolling(6, min_periods=2).mean()

    if "temp" in grid.columns:
        features["temp"] = grid["temp"]
        features["temp_d3h"] = _trailing_slope(grid["temp"], 3)

    if "abs_humidity" in grid.columns:
        abs_hum = grid["abs_humidity"]
    elif {"temp", "rh"} <= set(grid.columns):
        abs_hum = pd.Series(rl.absolute_humidity(grid["temp"], grid["rh"]), index=grid.index)
    else:
        abs_hum = None
    if abs_hum is not None:
        features["abs_hum"] = abs_hum
        features["abs_hum_d3h"] = _trailing_slope(abs_hum, 3)

    if "pressure" in grid.columns:
        pressure = grid["pressure"]
        features["pressure"] = pressure
        # Station-relative: absolute thresholds are meaningless at 220 m, where
        # the barometer's median reading is 989.6 hPa. A time-based window needs
        # a DatetimeIndex, so fall back to the equivalent row count elsewhere.
        window = "30D" if isinstance(grid.index, pd.DatetimeIndex) else BASELINE_ROWS
        features["pressure_anomaly"] = pressure - pressure.rolling(
            window, min_periods=24).median()
        for hours in (3, 6, 12, 24):
            features[f"pressure_d{hours}h"] = _trailing_slope(pressure, hours)

    if isinstance(grid.index, pd.DatetimeIndex):
        hour = grid.index.hour
        doy = grid.index.dayofyear
        features["hour_sin"] = np.sin(2 * np.pi * hour / 24)
        features["hour_cos"] = np.cos(2 * np.pi * hour / 24)
        features["doy_sin"] = np.sin(2 * np.pi * doy / 365)
        features["doy_cos"] = np.cos(2 * np.pi * doy / 365)

    return features[[c for c in FEATURE_COLUMNS if c in features.columns]]


@dataclass
class WalkForwardResult:
    """Out-of-sample predictions and the scores computed from them."""
    predictions: pd.Series
    roc_auc: float
    average_precision: float
    base_rate: float
    n_train_first: int
    n_scored: int
    folds: int
    features: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "roc_auc": None if np.isnan(self.roc_auc) else float(self.roc_auc),
            "average_precision": (None if np.isnan(self.average_precision)
                                  else float(self.average_precision)),
            "base_rate": float(self.base_rate),
            "n_scored": int(self.n_scored),
            "folds": int(self.folds),
            "features": list(self.features),
        }


def walk_forward(features: pd.DataFrame, truth: pd.Series, *,
                 folds: int = 5, min_train_frac: float = 0.4,
                 fit_predict=None) -> WalkForwardResult:
    """Expanding-window validation: always train on the past, score the future.

    The first `min_train_frac` of the labelled rows seeds the training set; the
    remainder is cut into `folds` blocks, and each block is predicted by a model
    fitted on everything before it. The returned predictions therefore contain
    no row that its own model had seen.

    `fit_predict(X_train, y_train, X_test) -> array` defaults to the calibrated
    logistic model; pass your own to compare a different learner on identical
    splits.
    """
    if fit_predict is None:
        fit_predict = _logistic_fit_predict

    aligned = features.join(truth.rename("__truth__"), how="inner").dropna()
    if aligned.empty:
        raise ValueError("walk_forward(): no rows with both features and a label")

    aligned = aligned.sort_index()
    y = aligned["__truth__"].to_numpy(dtype=float)
    X = aligned.drop(columns="__truth__")

    n = len(aligned)
    start = int(n * min_train_frac)
    if start < 2 or start >= n:
        raise ValueError(
            f"walk_forward(): {n} labelled rows cannot be split with "
            f"min_train_frac={min_train_frac}")

    bounds = np.unique(np.linspace(start, n, folds + 1).astype(int))
    out = np.full(n, np.nan)
    used_folds = 0

    for train_end, test_end in zip(bounds[:-1], bounds[1:]):
        if test_end <= train_end:
            continue
        y_train = y[:train_end]
        # A fold whose training window is single-class teaches nothing; leaving
        # its rows NaN is honest, filling them with a guess is not.
        if len(np.unique(y_train)) < 2:
            continue
        out[train_end:test_end] = fit_predict(X.iloc[:train_end], y_train, X.iloc[train_end:test_end])
        used_folds += 1

    predictions = pd.Series(out, index=aligned.index)
    scored = predictions.notna()

    return WalkForwardResult(
        predictions=predictions,
        roc_auc=rl.roc_auc(predictions, aligned["__truth__"]),
        average_precision=rl.average_precision(predictions, aligned["__truth__"]),
        base_rate=float(aligned["__truth__"][scored].mean()) if scored.any() else float("nan"),
        n_train_first=int(start),
        n_scored=int(scored.sum()),
        folds=used_folds,
        features=list(X.columns),
    )


def _make_pipeline():
    """Standardised logistic regression.

    No `class_weight="balanced"`: reweighting improves nothing in ranking terms
    here and it distorts the predicted probabilities, which are the reason for
    choosing this model over a tree ensemble.
    """
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError(
            "The learned model needs scikit-learn: pip install -r requirements.txt"
        ) from exc

    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))


def _logistic_fit_predict(X_train, y_train, X_test):
    model = _make_pipeline()
    model.fit(X_train, y_train)
    return model.predict_proba(X_test)[:, 1]


def fit(features: pd.DataFrame, truth: pd.Series):
    """Fit the model on every labelled row. For deployment, not for scoring."""
    aligned = features.join(truth.rename("__truth__"), how="inner").dropna()
    if aligned.empty:
        raise ValueError("fit(): no rows with both features and a label")
    y = aligned["__truth__"].to_numpy(dtype=float)
    if len(np.unique(y)) < 2:
        raise ValueError("fit(): the training window contains only one class")

    X = aligned.drop(columns="__truth__")
    model = _make_pipeline()
    model.fit(X, y)
    return model, list(X.columns)


def coefficients(model, feature_names: list[str]) -> dict[str, float]:
    """Standardised coefficients — comparable across features, unlike raw ones."""
    logistic = model[-1]
    return {name: float(weight)
            for name, weight in zip(feature_names, logistic.coef_[0])}


def save(model, feature_names: list[str], path: str | Path, *,
         metadata: dict | None = None) -> Path:
    """Persist a fitted model together with what it was trained on.

    A deployed model that cannot be traced back to its training window, feature
    list and measured held-out score is not reproducible, and quietly becomes
    the thing nobody dares to touch. The sidecar JSON is written so that record
    stays readable without unpickling anything.
    """
    try:
        import joblib
    except ImportError as exc:  # pragma: no cover
        raise ImportError("Saving the model needs joblib (installed with scikit-learn)") from exc

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "features": feature_names}, path)

    record = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "features": feature_names,
        "coefficients": coefficients(model, feature_names),
        **(metadata or {}),
    }
    path.with_suffix(".json").write_text(json.dumps(record, indent=2, default=str))
    return path


def load(path: str | Path):
    """Load a model saved by `save()`. Returns (model, feature_names)."""
    try:
        import joblib
    except ImportError as exc:  # pragma: no cover
        raise ImportError("Loading the model needs joblib (installed with scikit-learn)") from exc

    payload = joblib.load(Path(path))
    return payload["model"], payload["features"]


def predict(model, feature_names: list[str], features: pd.DataFrame) -> pd.Series:
    """Predicted rain probability in percent, aligned to the feature index.

    Rows with any missing feature yield NaN rather than an imputed guess — the
    rest of the pipeline already treats NaN as "no opinion".
    """
    missing = [c for c in feature_names if c not in features.columns]
    if missing:
        raise ValueError(f"predict(): feature frame is missing {missing}")

    usable = features[feature_names].dropna()
    out = pd.Series(np.nan, index=features.index)
    if not usable.empty:
        out.loc[usable.index] = model.predict_proba(usable)[:, 1] * 100.0
    return out
