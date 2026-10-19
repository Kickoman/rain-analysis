"""Tests for model caching.

Verifies that the in-memory ModelCache avoids repeated disk reads, supports
independent per-model caching and clearing, enforces the singleton pattern,
and is safe under concurrent access.
"""

import pickle
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.ml.model_loader import ModelCache


class SimpleMockModel:
    """Simple mock model that can be pickled."""

    def __init__(self):
        self.name = "mock_model"

    def predict_proba(self, X):
        """Mock predict_proba method."""
        return [[0.3, 0.7], [0.6, 0.4]]


@pytest.fixture
def sample_model_file():
    """Create a temporary pickle file with a mock model."""
    mock_model = SimpleMockModel()
    with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".pkl") as f:
        pickle.dump(mock_model, f)
        temp_path = Path(f.name)

    yield temp_path

    if temp_path.exists():
        temp_path.unlink()


@pytest.fixture
def temp_models_dir():
    """Create a temporary directory for models."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def model_cache(temp_models_dir):
    """Create a fresh ModelCache instance."""
    return ModelCache(models_dir=temp_models_dir)


class TestModelCache:
    """Model cache behavior tests."""

    def test_cache_avoids_reload_on_hit(self, model_cache, sample_model_file, monkeypatch):
        """A cache hit returns the same object without reading the file again."""
        import app.ml.model_loader as model_loader

        real_load = model_loader.pickle.load
        calls = []

        def counting_load(f, *args, **kwargs):
            calls.append(f)
            return real_load(f, *args, **kwargs)

        monkeypatch.setattr(model_loader.pickle, "load", counting_load)

        model1 = model_cache.load_model("test-model", sample_model_file)
        model2 = model_cache.load_model("test-model", sample_model_file)

        assert model1 is model2
        assert len(calls) == 1

    def test_cache_clear(self, model_cache, sample_model_file):
        """Clearing a model forces a reload from disk."""
        model1 = model_cache.load_model("test-model", sample_model_file)
        model_cache.clear_cache("test-model")
        model2 = model_cache.load_model("test-model", sample_model_file)

        assert model1 is not model2

    def test_multiple_models_cached(self, model_cache, sample_model_file):
        """Different model names are cached independently."""
        model_a = model_cache.load_model("model-a", sample_model_file)
        model_b = model_cache.load_model("model-b", sample_model_file)

        assert model_a is not model_b

        assert model_cache.load_model("model-a", sample_model_file) is model_a
        assert model_cache.load_model("model-b", sample_model_file) is model_b

    def test_cache_clear_specific_model(self, model_cache, sample_model_file):
        """Clearing one model does not affect others."""
        model_a = model_cache.load_model("model-a", sample_model_file)
        model_b = model_cache.load_model("model-b", sample_model_file)

        model_cache.clear_cache("model-a")

        assert model_cache.load_model("model-a", sample_model_file) is not model_a
        assert model_cache.load_model("model-b", sample_model_file) is model_b

    def test_singleton_pattern(self, temp_models_dir):
        """get_model_cache returns a single shared instance."""
        import app.ml.model_loader as model_loader
        from app.ml.model_loader import get_model_cache

        original = model_loader._model_cache
        try:
            model_loader._model_cache = None
            cache1 = get_model_cache(temp_models_dir)
            cache2 = get_model_cache(temp_models_dir)
            assert cache1 is cache2
        finally:
            model_loader._model_cache = original

    def test_nonexistent_file_error(self, model_cache):
        """Loading a missing file raises FileNotFoundError."""
        nonexistent_path = Path("/tmp/nonexistent_model_12345.pkl")
        with pytest.raises(FileNotFoundError):
            model_cache.load_model("test-model", nonexistent_path)

    def test_get_cached_models(self, model_cache, sample_model_file):
        """get_cached_models lists models currently held in cache."""
        model_cache.load_model("stats-test", sample_model_file)
        model_cache.load_model("stats-test", sample_model_file)

        assert "stats-test" in model_cache.get_cached_models()


class TestModelCacheConcurrency:
    """Model cache behavior under concurrent access."""

    def test_concurrent_loads(self, model_cache, sample_model_file):
        """Concurrent loads of the same model return the same cached object."""
        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(
                ex.map(
                    lambda _: model_cache.load_model("concurrent-test", sample_model_file),
                    range(8),
                )
            )

        assert all(r is results[0] for r in results)
