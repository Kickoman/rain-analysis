"""Tests for ModelCache and model loading functionality."""

import pytest
import pickle
from pathlib import Path
import sys
from unittest.mock import Mock

# Add backend/app to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))

from ml.model_loader import ModelCache, get_model_cache


class DummyModel:
    """Mock model for testing."""
    
    def __init__(self, name: str):
        self.name = name
        self.call_count = 0
    
    def predict_proba(self, X):
        """Mock prediction method."""
        self.call_count += 1
        return [[0.3, 0.7]] * len(X)


@pytest.fixture
def temp_models_dir(tmp_path):
    """Create temporary models directory with test models."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    
    # Create dummy model files
    model1 = DummyModel("test_model_1")
    model2 = DummyModel("test_model_2")
    
    with open(models_dir / "test_model_1.pkl", "wb") as f:
        pickle.dump(model1, f)
    
    with open(models_dir / "test_model_2.pkl", "wb") as f:
        pickle.dump(model2, f)
    
    return models_dir


@pytest.fixture
def model_cache(temp_models_dir):
    """Create ModelCache instance with temporary directory."""
    return ModelCache(temp_models_dir)


def test_model_cache_initialization(temp_models_dir):
    """Test ModelCache initialization."""
    cache = ModelCache(temp_models_dir)
    assert cache.models_dir == temp_models_dir
    assert len(cache._cache) == 0


def test_load_model_from_file(model_cache):
    """Test loading model from pickle file."""
    model = model_cache.load_model("test_model_1")
    
    assert model is not None
    assert isinstance(model, DummyModel)
    assert model.name == "test_model_1"
    assert len(model_cache._cache) == 1


def test_load_model_from_cache(model_cache):
    """Test that subsequent loads return cached instance."""
    # First load
    model1 = model_cache.load_model("test_model_1")
    assert len(model_cache._cache) == 1
    
    # Second load should return same instance
    model2 = model_cache.load_model("test_model_1")
    assert model1 is model2
    assert len(model_cache._cache) == 1


def test_load_multiple_models(model_cache):
    """Test loading multiple models."""
    model1 = model_cache.load_model("test_model_1")
    model2 = model_cache.load_model("test_model_2")
    
    assert model1.name == "test_model_1"
    assert model2.name == "test_model_2"
    assert len(model_cache._cache) == 2


def test_load_model_with_custom_path(model_cache, temp_models_dir):
    """Test loading model with explicit file path."""
    custom_path = temp_models_dir / "test_model_1.pkl"
    model = model_cache.load_model("custom_key", file_path=custom_path)
    
    assert model.name == "test_model_1"
    assert "custom_key" in model_cache._cache


def test_load_nonexistent_model(model_cache):
    """Test that loading nonexistent model raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        model_cache.load_model("nonexistent_model")


def test_clear_cache_single_model(model_cache):
    """Test clearing cache for single model."""
    # Load models
    model_cache.load_model("test_model_1")
    model_cache.load_model("test_model_2")
    assert len(model_cache._cache) == 2
    
    # Clear one model
    model_cache.clear_cache("test_model_1")
    assert len(model_cache._cache) == 1
    assert "test_model_1" not in model_cache._cache
    assert "test_model_2" in model_cache._cache


def test_clear_cache_all_models(model_cache):
    """Test clearing entire cache."""
    # Load models
    model_cache.load_model("test_model_1")
    model_cache.load_model("test_model_2")
    assert len(model_cache._cache) == 2
    
    # Clear all
    model_cache.clear_cache()
    assert len(model_cache._cache) == 0


def test_clear_cache_nonexistent_model(model_cache):
    """Test clearing nonexistent model doesn't raise error."""
    model_cache.clear_cache("nonexistent_model")  # Should not raise


def test_get_cached_models(model_cache):
    """Test getting list of cached model names."""
    assert model_cache.get_cached_models() == []
    
    model_cache.load_model("test_model_1")
    assert model_cache.get_cached_models() == ["test_model_1"]
    
    model_cache.load_model("test_model_2")
    cached = model_cache.get_cached_models()
    assert len(cached) == 2
    assert "test_model_1" in cached
    assert "test_model_2" in cached


def test_get_model_cache_singleton(temp_models_dir):
    """Test that get_model_cache returns singleton instance."""
    # Reset global singleton for clean test
    import ml.model_loader as loader_module
    loader_module._model_cache = None
    
    cache1 = get_model_cache(temp_models_dir)
    cache2 = get_model_cache()
    
    assert cache1 is cache2
    
    # Cleanup
    loader_module._model_cache = None


def test_get_model_cache_without_dir_raises():
    """Test that get_model_cache raises if called without dir on first use."""
    import ml.model_loader as loader_module
    loader_module._model_cache = None
    
    with pytest.raises(ValueError, match="models_dir required"):
        get_model_cache()
    
    # Cleanup
    loader_module._model_cache = None
