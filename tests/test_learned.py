"""
Tests for the fitted model and its validation harness.

A fitted model is worth exactly what its validation is worth, so most of what
follows tests the harness rather than the learner. Two properties carry the
weight:

- **Features are causal.** Weather is autocorrelated, so a feature that peeks
  even one hour ahead produces a model that scores beautifully and forecasts
  nothing.
- **Folds never train on what they score.** Expanding window only, always
  forward in time.

Measured on the 43-day archive over identical held-out rows, the logistic model
reaches ROC AUC 0.753 on the 3-hour warning target against 0.669 for the best
hand-tuned model and 0.494 for the production replica.
"""

import numpy as np
import pandas as pd
import pytest

import learned
import rainlib as rl


def grid(n=600, seed=0, start="2026-06-01"):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({
        "temp": 18 + rng.normal(0, 3, n).cumsum() * 0.05,
        "rh": np.clip(65 + rng.normal(0, 8, n), 5, 100),
        "pressure": 990 + rng.normal(0, 2, n).cumsum() * 0.05,
    }, index=idx)


def truth_for(frame, seed=1, rate=0.25):
    rng = np.random.default_rng(seed)
    return pd.Series((rng.random(len(frame)) < rate).astype(float), index=frame.index)


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------

def test_builds_the_expected_columns():
    features = learned.build_features(grid())
    assert set(features.columns) <= set(learned.FEATURE_COLUMNS)
    assert {"pressure", "pressure_anomaly", "spread", "rh", "hour_sin"} <= set(features.columns)


def test_column_order_is_stable():
    """A model is saved with its feature list; reordering would silently rebind it."""
    features = learned.build_features(grid())
    assert list(features.columns) == [c for c in learned.FEATURE_COLUMNS
                                      if c in features.columns]


def test_features_are_causal():
    """The property everything else depends on: no row may see its own future."""
    base = grid()
    tampered = base.copy()
    tampered.iloc[-50:, :] = tampered.iloc[-50:, :] * 3.0

    before = learned.build_features(base).iloc[:-50]
    after = learned.build_features(tampered).iloc[:-50]

    pd.testing.assert_frame_equal(before, after)


def test_pressure_anomaly_is_station_relative():
    """Two stations differing only by elevation must produce the same anomaly."""
    low = grid()
    high = low.copy()
    high["pressure"] = high["pressure"] + 25.0

    pd.testing.assert_series_equal(
        learned.build_features(low)["pressure_anomaly"],
        learned.build_features(high)["pressure_anomaly"],
    )


def test_works_without_a_barometer():
    """The archive has no pressure before 2026-07-12; the rest must still build."""
    features = learned.build_features(grid().drop(columns="pressure"))
    assert "pressure" not in features.columns
    assert "spread" in features.columns


def test_accepts_a_precomputed_spread():
    frame = grid()
    frame["spread"] = 3.0
    assert learned.build_features(frame)["spread"].iloc[0] == pytest.approx(3.0)


def test_needs_something_to_work_from():
    with pytest.raises(ValueError, match="need either"):
        learned.build_features(pd.DataFrame({"pressure": [1000.0, 1001.0]}))


def test_clock_features_are_omitted_without_a_datetime_index():
    frame = grid().reset_index(drop=True)
    features = learned.build_features(frame)
    assert "hour_sin" not in features.columns


# ---------------------------------------------------------------------------
# Walk-forward validation
# ---------------------------------------------------------------------------

def test_only_the_later_rows_are_scored():
    frame = grid()
    result = learned.walk_forward(learned.build_features(frame), truth_for(frame))

    scored = result.predictions.dropna()
    assert 0 < len(scored) < len(result.predictions)
    # everything scored comes after everything used to seed training
    assert scored.index.min() > result.predictions.index.min()


def test_no_row_is_predicted_by_a_model_that_saw_it():
    """Recorded explicitly: each fold's predictions come from earlier rows only."""
    frame = grid()
    features = learned.build_features(frame)
    truth = truth_for(frame)
    seen = []

    def spy(X_train, y_train, X_test):
        seen.append((X_train.index.max(), X_test.index.min()))
        return np.full(len(X_test), 0.5)

    learned.walk_forward(features, truth, fit_predict=spy)

    assert seen
    for train_end, test_start in seen:
        assert train_end < test_start


def test_folds_expand():
    frame = grid()
    sizes = []

    def spy(X_train, y_train, X_test):
        sizes.append(len(X_train))
        return np.full(len(X_test), 0.5)

    learned.walk_forward(learned.build_features(frame), truth_for(frame), fit_predict=spy)
    assert sizes == sorted(sizes)
    assert len(set(sizes)) > 1


def test_chance_predictions_score_as_chance():
    frame = grid()
    result = learned.walk_forward(
        learned.build_features(frame), truth_for(frame),
        fit_predict=lambda Xtr, ytr, Xte: np.full(len(Xte), 0.5))

    assert result.roc_auc == pytest.approx(0.5)


def test_a_leaked_label_scores_perfectly():
    """Sanity check on the harness itself — if this did not hit 1.0 it is broken."""
    frame = grid()
    truth = truth_for(frame)

    result = learned.walk_forward(
        learned.build_features(frame), truth,
        fit_predict=lambda Xtr, ytr, Xte: truth.reindex(Xte.index).to_numpy())

    assert result.roc_auc == pytest.approx(1.0)


def test_single_class_fold_is_left_unscored():
    """Better an honest gap than a fabricated prediction."""
    frame = grid(n=300)
    truth = pd.Series(0.0, index=frame.index)
    truth.iloc[-5:] = 1.0     # positives only in the final fold

    result = learned.walk_forward(learned.build_features(frame), truth)
    assert result.folds < 5


def test_too_little_data_is_refused():
    """Enough rows to be usable, too few to hold any back."""
    idx = pd.date_range("2026-07-01", periods=4, freq="1h", tz="UTC")
    features = pd.DataFrame({"spread": [1.0, 2.0, 3.0, 4.0]}, index=idx)
    truth = pd.Series([0.0, 1.0, 0.0, 1.0], index=idx)

    with pytest.raises(ValueError, match="cannot be split"):
        learned.walk_forward(features, truth)


def test_no_usable_rows_is_refused():
    frame = grid(n=6)
    with pytest.raises(ValueError, match="no rows with both features and a label"):
        learned.walk_forward(learned.build_features(frame), truth_for(frame))


def test_unlabelled_rows_are_dropped_not_guessed():
    frame = grid()
    truth = truth_for(frame)
    truth.iloc[100:200] = np.nan

    result = learned.walk_forward(learned.build_features(frame), truth)
    assert not result.predictions.index.isin(truth.index[100:200]).any()


def test_result_serialises():
    frame = grid()
    payload = learned.walk_forward(learned.build_features(frame), truth_for(frame)).to_dict()

    assert set(payload) >= {"roc_auc", "average_precision", "base_rate", "n_scored", "folds"}
    assert isinstance(payload["features"], list)


# ---------------------------------------------------------------------------
# Fitting, prediction and persistence
# ---------------------------------------------------------------------------

def test_learns_a_real_signal():
    """With a genuine relationship the model must find it."""
    frame = grid(n=800)
    features = learned.build_features(frame)
    # rain when pressure sits below its own normal
    truth = (features["pressure_anomaly"] < -0.5).astype(float)

    result = learned.walk_forward(features, truth)
    assert result.roc_auc > 0.8


def test_predict_returns_percent_and_keeps_the_index():
    frame = grid()
    features = learned.build_features(frame)
    truth = truth_for(frame)

    model, names = learned.fit(features, truth)
    predictions = learned.predict(model, names, features)

    assert predictions.index.equals(features.index)
    valid = predictions.dropna()
    assert valid.min() >= 0 and valid.max() <= 100


def test_predict_yields_nan_for_incomplete_rows():
    """No imputed guesses — NaN already means 'no opinion' downstream."""
    frame = grid()
    features = learned.build_features(frame)
    model, names = learned.fit(features, truth_for(frame))

    holed = features.copy()
    holed.iloc[5, 0] = np.nan
    assert np.isnan(learned.predict(model, names, holed).iloc[5])


def test_predict_rejects_a_mismatched_feature_frame():
    frame = grid()
    features = learned.build_features(frame)
    model, names = learned.fit(features, truth_for(frame))

    with pytest.raises(ValueError, match="missing"):
        learned.predict(model, names, features.drop(columns=names[0]))


def test_fit_refuses_a_single_class_window():
    frame = grid()
    with pytest.raises(ValueError, match="only one class"):
        learned.fit(learned.build_features(frame), pd.Series(0.0, index=frame.index))


def test_coefficients_are_named_and_comparable():
    frame = grid()
    features = learned.build_features(frame)
    model, names = learned.fit(features, truth_for(frame))

    coefficients = learned.coefficients(model, names)
    assert set(coefficients) == set(names)
    assert all(isinstance(v, float) for v in coefficients.values())


def test_save_load_roundtrip_preserves_predictions(tmp_path):
    frame = grid()
    features = learned.build_features(frame)
    model, names = learned.fit(features, truth_for(frame))

    path = learned.save(model, names, tmp_path / "model.joblib",
                        metadata={"trained_on": "2026-07-01..2026-08-13"})
    reloaded, reloaded_names = learned.load(path)

    assert reloaded_names == names
    pd.testing.assert_series_equal(
        learned.predict(model, names, features),
        learned.predict(reloaded, reloaded_names, features),
    )


def test_saved_model_records_its_provenance(tmp_path):
    """A deployed model that cannot be traced to its training data is a liability."""
    import json

    frame = grid()
    features = learned.build_features(frame)
    model, names = learned.fit(features, truth_for(frame))

    path = learned.save(model, names, tmp_path / "model.joblib",
                        metadata={"trained_on": "2026-07-01..2026-08-13",
                                  "holdout_roc_auc": 0.753})
    record = json.loads(path.with_suffix(".json").read_text())

    assert record["features"] == names
    assert record["trained_on"] == "2026-07-01..2026-08-13"
    assert record["holdout_roc_auc"] == 0.753
    assert set(record["coefficients"]) == set(names)
    assert record["saved_at"]
