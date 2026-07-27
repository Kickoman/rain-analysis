"""ML service layer for rain prediction models.

This module provides:
- rainlib.py: Core rain prediction models and physics functions
- model_loader.py: Model caching and loading from pickle files
- prediction_service.py: Prediction generation and database storage
"""

# Lazy imports to avoid circular dependencies and relative import issues
__all__ = [
    "ModelCache",
    "get_model_cache",
    "PredictionService",
]


def __getattr__(name):
    """Lazy import on attribute access."""
    if name == "ModelCache":
        from .model_loader import ModelCache
        return ModelCache
    elif name == "get_model_cache":
        from .model_loader import get_model_cache
        return get_model_cache
    elif name == "PredictionService":
        from .prediction_service import PredictionService
        return PredictionService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
