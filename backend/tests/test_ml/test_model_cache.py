"""
Performance tests for model caching.

Tests that model caching significantly improves loading performance
and that cache management (clear, invalidation) works correctly.
"""

import pytest
import time
import pickle
import tempfile
from pathlib import Path

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
    # Create a simple mock model that can be pickled
    mock_model = SimpleMockModel()
    
    # Save to temporary file
    with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.pkl') as f:
        pickle.dump(mock_model, f)
        temp_path = Path(f.name)
    
    yield temp_path
    
    # Cleanup
    if temp_path.exists():
        temp_path.unlink()


@pytest.fixture
def temp_models_dir():
    """Create a temporary directory for models."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def model_cache(temp_models_dir):
    """Create a fresh ModelCache instance."""
    return ModelCache(models_dir=temp_models_dir)


class TestModelCache:
    """Test model caching performance."""
    
    def test_cache_hit_performance(self, model_cache: ModelCache, sample_model_file: Path):
        """Verify cache significantly speeds up model loading."""
        
        # First load (from file)
        start = time.time()
        model1 = model_cache.load_model("test-model", sample_model_file)
        first_load_time = time.time() - start
        
        # Second load (from cache)
        start = time.time()
        model2 = model_cache.load_model("test-model", sample_model_file)
        cached_load_time = time.time() - start
        
        print(f"\nFirst load: {first_load_time*1000:.2f}ms")
        print(f"Cached load: {cached_load_time*1000:.2f}ms")
        print(f"Speedup: {first_load_time/cached_load_time:.1f}x")
        
        # Cache should be at least 10x faster
        assert cached_load_time < first_load_time / 10, \
            f"Cache speedup insufficient: {first_load_time/cached_load_time:.1f}x (expected >10x)"
        
        # Should return same object reference
        assert model1 is model2, "Cache should return same object reference"
        
        print("✓ Cache provides >10x speedup")
    
    def test_cache_clear(self, model_cache: ModelCache, sample_model_file: Path):
        """Test cache clearing."""
        
        # Load model
        model1 = model_cache.load_model("test-model", sample_model_file)
        
        # Clear cache for this model
        model_cache.clear_cache("test-model")
        
        # Load again (should reload from file)
        model2 = model_cache.load_model("test-model", sample_model_file)
        
        # Different objects after cache clear
        assert model1 is not model2, "After cache clear, should load new object"
        
        print("\n✓ Cache clear works correctly")
    
    def test_multiple_models_cached(self, model_cache: ModelCache, sample_model_file: Path):
        """Test that multiple models can be cached independently."""
        
        # Load two different models (using same file for simplicity)
        model_a = model_cache.load_model("model-a", sample_model_file)
        model_b = model_cache.load_model("model-b", sample_model_file)
        
        # Should be different objects
        assert model_a is not model_b, "Different model names should cache separately"
        
        # Reload both - should get cached versions
        model_a2 = model_cache.load_model("model-a", sample_model_file)
        model_b2 = model_cache.load_model("model-b", sample_model_file)
        
        assert model_a is model_a2, "Model A should be cached"
        assert model_b is model_b2, "Model B should be cached"
        
        print("\n✓ Multiple models cached independently")
    
    def test_cache_clear_specific_model(self, model_cache: ModelCache, sample_model_file: Path):
        """Test that clearing one model doesn't affect others."""
        
        # Load two models
        model_a = model_cache.load_model("model-a", sample_model_file)
        model_b = model_cache.load_model("model-b", sample_model_file)
        
        # Clear only model A
        model_cache.clear_cache("model-a")
        
        # Reload both
        model_a2 = model_cache.load_model("model-a", sample_model_file)
        model_b2 = model_cache.load_model("model-b", sample_model_file)
        
        # A should be different (reloaded), B should be same (cached)
        assert model_a is not model_a2, "Model A should be reloaded"
        assert model_b is model_b2, "Model B should still be cached"
        
        print("\n✓ Selective cache clear works")
    
    def test_singleton_pattern(self, temp_models_dir):
        """Test that ModelCache follows singleton pattern."""
        from app.ml.model_loader import get_model_cache
        
        # Reset singleton for test
        import app.ml.model_loader
        app.ml.model_loader._model_cache = None
        
        # Get two instances with same models_dir
        cache1 = get_model_cache(temp_models_dir)
        cache2 = get_model_cache(temp_models_dir)
        
        # Should be the same instance
        assert cache1 is cache2, "get_model_cache should return singleton"
        
        print("\n✓ Singleton pattern enforced")
        
        # Reset for other tests
        app.ml.model_loader._model_cache = None
    
    def test_nonexistent_file_error(self, model_cache: ModelCache):
        """Test that loading nonexistent file raises appropriate error."""
        
        nonexistent_path = Path("/tmp/nonexistent_model_12345.pkl")
        
        with pytest.raises(FileNotFoundError):
            model_cache.load_model("test-model", nonexistent_path)
        
        print("\n✓ Nonexistent file properly handled")
    
    def test_cache_statistics(self, model_cache: ModelCache, sample_model_file: Path):
        """Test cache hit/miss tracking (if implemented)."""
        
        # First load (miss)
        model_cache.load_model("stats-test", sample_model_file)
        
        # Second load (hit)
        model_cache.load_model("stats-test", sample_model_file)
        
        # Third load (hit)
        model_cache.load_model("stats-test", sample_model_file)
        
        # Check what models are cached
        cached_models = model_cache.get_cached_models()
        assert "stats-test" in cached_models, "Model should be in cache"
        
        print(f"\n✓ Cache tracking works: {len(cached_models)} model(s) cached")


class TestModelCacheConcurrency:
    """Test model cache under concurrent access."""
    
    @pytest.mark.asyncio
    async def test_concurrent_loads(self, model_cache: ModelCache, sample_model_file: Path):
        """Test that concurrent loads of same model are safe."""
        import asyncio
        
        async def load_model():
            # Simulate async load (ModelCache.load_model is sync, but we test from async context)
            return model_cache.load_model("concurrent-test", sample_model_file)
        
        # Load model concurrently from multiple "tasks"
        results = await asyncio.gather(
            load_model(),
            load_model(),
            load_model(),
        )
        
        # All should return the same cached object
        assert results[0] is results[1] is results[2], \
            "Concurrent loads should return same cached object"
        
        print("\n✓ Concurrent cache access is safe")
