"""Tests for PredictionService against real models and a real session."""

import pickle

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from app.ml.prediction_service import PredictionService
from app.models.ml import MLModel, Prediction

BASE_TS = datetime(2026, 8, 20, 0, 0, tzinfo=timezone.utc)


class StubEstimator:
    """Minimal sklearn-like estimator: p = spread / 10 clipped to [0, 1]."""

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        p = np.clip(features["spread"].to_numpy(dtype=float) / 10.0, 0.0, 1.0)
        return np.column_stack([1.0 - p, p])


class PredictOnlyEstimator:
    def predict(self, features: pd.DataFrame) -> np.ndarray:
        return np.full(len(features), 0.42)


@pytest.fixture
def models_dir(tmp_path, monkeypatch):
    """Point the model cache at a temp dir with the stub pickle in it."""
    with open(tmp_path / "stub_model.pkl", "wb") as f:
        pickle.dump(StubEstimator(), f)
    with open(tmp_path / "predict_only.pkl", "wb") as f:
        pickle.dump(PredictOnlyEstimator(), f)
    from app.config import settings
    monkeypatch.setattr(settings, "models_dir", str(tmp_path))
    return tmp_path


async def make_model(db_session, name="stub_model", config=None) -> MLModel:
    model = MLModel(
        name=name,
        version="1",
        config=config if config is not None else {"threshold": 0.5},
        active=True,
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    return model


def features_frame(spreads):
    index = pd.DatetimeIndex([BASE_TS + timedelta(hours=i) for i in range(len(spreads))])
    return pd.DataFrame({"spread": spreads}, index=index)


@pytest.mark.asyncio
async def test_get_active_models(db_session, models_dir):
    await make_model(db_session, "active_one")
    inactive = MLModel(name="inactive_one", version="1", config={}, active=False)
    db_session.add(inactive)
    await db_session.commit()

    service = PredictionService(db_session)
    models = await service.get_active_models()
    assert [m.name for m in models] == ["active_one"]


@pytest.mark.asyncio
async def test_predict_with_predict_proba(db_session, models_dir):
    model = await make_model(db_session)
    service = PredictionService(db_session)

    probs = service.predict(model, features_frame([2.0, 5.0, 20.0]))
    assert probs == pytest.approx([0.2, 0.5, 1.0])


@pytest.mark.asyncio
async def test_predict_with_predict_fallback(db_session, models_dir):
    model = await make_model(db_session, "predict_only")
    service = PredictionService(db_session)

    probs = service.predict(model, features_frame([1.0, 2.0]))
    assert probs == pytest.approx([0.42, 0.42])


@pytest.mark.asyncio
async def test_predict_respects_file_path_config(db_session, models_dir):
    """config["file_path"] overrides the {name}.pkl convention."""
    model = await make_model(
        db_session, "renamed_model", config={"file_path": "stub_model.pkl"}
    )
    service = PredictionService(db_session)

    probs = service.predict(model, features_frame([5.0]))
    assert probs == pytest.approx([0.5])


@pytest.mark.asyncio
async def test_predict_selects_configured_features(db_session, models_dir):
    """Extra columns are dropped per config["features"]; missing ones raise."""
    model = await make_model(
        db_session, "stub_model", config={"features": ["spread"]}
    )
    service = PredictionService(db_session)

    frame = features_frame([5.0])
    frame["noise"] = 123.0
    assert service.predict(model, frame) == pytest.approx([0.5])

    model_missing = await make_model(
        db_session, "stub_model_missing", config={"features": ["spread", "absent"]}
    )
    with pytest.raises(ValueError, match="missing features"):
        service.predict(model_missing, frame)


@pytest.mark.asyncio
async def test_predict_rainlib_kind(db_session, models_dir):
    model = await make_model(
        db_session, "replica", config={"kind": "rainlib", "rainlib_model": "ha_live"}
    )
    service = PredictionService(db_session)

    probs = service.predict(model, features_frame([8.0, 4.0, 0.5, 8.0, 4.0, 0.5]))
    assert len(probs) == 6
    assert all(0.0 <= p <= 1.0 for p in probs)
    # Smaller dew-point spread must not lower the probability
    assert probs[2] >= probs[1] >= probs[0]


@pytest.mark.asyncio
async def test_predict_unknown_kind_raises(db_session, models_dir):
    model = await make_model(db_session, "weird", config={"kind": "quantum"})
    service = PredictionService(db_session)
    with pytest.raises(ValueError, match="Unknown model kind"):
        service.predict(model, features_frame([1.0]))


@pytest.mark.asyncio
async def test_predict_missing_pickle_raises(db_session, models_dir):
    model = await make_model(db_session, "no_such_model")
    service = PredictionService(db_session)
    with pytest.raises(FileNotFoundError):
        service.predict(model, features_frame([1.0]))


@pytest.mark.asyncio
async def test_predict_and_store(db_session, models_dir):
    model = await make_model(db_session)
    service = PredictionService(db_session)

    frame = features_frame([2.0, 5.0, 9.0])
    timestamps = [ts.to_pydatetime() for ts in frame.index]
    stored = await service.predict_and_store(model.id, frame, timestamps)
    assert stored == 3

    rows = (
        await db_session.execute(
            select(Prediction).where(Prediction.model_id == model.id).order_by(Prediction.timestamp)
        )
    ).scalars().all()
    assert [r.probability for r in rows] == pytest.approx([0.2, 0.5, 0.9])
    assert [r.binary_prediction for r in rows] == [False, True, True]
    assert all(r.threshold == 0.5 for r in rows)


@pytest.mark.asyncio
async def test_predict_and_store_upserts(db_session, models_dir):
    model = await make_model(db_session)
    service = PredictionService(db_session)

    frame = features_frame([2.0, 5.0])
    timestamps = [ts.to_pydatetime() for ts in frame.index]
    await service.predict_and_store(model.id, frame, timestamps)

    frame2 = features_frame([9.0, 9.0])
    stored = await service.predict_and_store(model.id, frame2, timestamps)
    assert stored == 2

    rows = (
        await db_session.execute(select(Prediction).where(Prediction.model_id == model.id))
    ).scalars().all()
    assert len(rows) == 2
    assert all(r.probability == pytest.approx(0.9) for r in rows)


@pytest.mark.asyncio
async def test_predict_and_store_custom_threshold(db_session, models_dir):
    model = await make_model(db_session)
    service = PredictionService(db_session)

    frame = features_frame([5.0])
    await service.predict_and_store(
        model.id, frame, [frame.index[0].to_pydatetime()], threshold=0.3
    )
    row = (await db_session.execute(select(Prediction))).scalar_one()
    assert row.threshold == 0.3
    assert row.binary_prediction is True


@pytest.mark.asyncio
async def test_predict_and_store_length_mismatch(db_session, models_dir):
    model = await make_model(db_session)
    service = PredictionService(db_session)
    with pytest.raises(ValueError, match="length mismatch"):
        await service.predict_and_store(model.id, features_frame([1.0, 2.0]), [BASE_TS])


@pytest.mark.asyncio
async def test_predict_and_store_model_not_found(db_session, models_dir):
    service = PredictionService(db_session)
    with pytest.raises(ValueError, match="not found"):
        await service.predict_and_store(999, features_frame([1.0]), [BASE_TS])


@pytest.mark.asyncio
async def test_get_predictions_with_time_range(db_session, models_dir):
    model = await make_model(db_session)
    service = PredictionService(db_session)

    frame = features_frame([1.0, 2.0, 3.0, 4.0])
    timestamps = [ts.to_pydatetime() for ts in frame.index]
    await service.predict_and_store(model.id, frame, timestamps)

    all_rows = await service.get_predictions(model.id)
    assert len(all_rows) == 4

    subset = await service.get_predictions(
        model.id,
        start_time=BASE_TS + timedelta(hours=1),
        end_time=BASE_TS + timedelta(hours=2),
    )
    assert len(subset) == 2
