"""Tests for ML module initialization."""

def test_ml_module_imports():
    """Test that ML module exports are available."""
    from backend.app.ml import ModelCache, get_model_cache, PredictionService
    
    assert ModelCache is not None
    assert get_model_cache is not None
    assert PredictionService is not None
