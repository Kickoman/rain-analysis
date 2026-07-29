"""Model loading and caching for ML models.

Provides in-memory caching of trained models loaded from pickle files.
Thread-safe singleton pattern ensures one cache instance per application.
"""

from typing import Dict, Optional, Any
from pathlib import Path
import pickle
import logging
import threading

logger = logging.getLogger(__name__)


class ModelCache:
    """In-memory cache for loaded ML models.
    
    Models are loaded from pickle files and cached to avoid repeated
    disk I/O. Cache is cleared on model updates or explicit invalidation.
    
    Thread-safety: This implementation uses threading.Lock for thread-safe
    cache access in multi-threaded environments (e.g., FastAPI with multiple
    workers or async concurrent requests).
    """
    
    def __init__(self, models_dir: Path):
        """Initialize model cache.
        
        Args:
            models_dir: Directory containing model pickle files
        """
        self.models_dir = Path(models_dir)
        self._cache: Dict[str, Any] = {}
        self._lock = threading.Lock()
        logger.info(f"ModelCache initialized with models_dir={self.models_dir}")
    
    def load_model(self, model_name: str, file_path: Optional[Path] = None) -> Any:
        """Load model from file or return cached instance.
        
        Uses double-checked locking pattern for thread-safe cache access:
        - Fast path: check cache without lock
        - Slow path: acquire lock, check again, load from disk if needed
        
        Args:
            model_name: Unique model identifier (cache key)
            file_path: Optional path to pickle file. If None, defaults to
                      {models_dir}/{model_name}.pkl
        
        Returns:
            Loaded model object (typically scikit-learn estimator or custom class)
        
        Raises:
            FileNotFoundError: If model file doesn't exist
            pickle.UnpicklingError: If file is corrupted or incompatible
        """
        # Fast path: return from cache if available (no lock needed for read)
        if model_name in self._cache:
            logger.debug(f"Model '{model_name}' loaded from cache")
            return self._cache[model_name]
        
        # Slow path: acquire lock for cache miss
        with self._lock:
            # Double-check: another thread might have loaded it while we waited
            if model_name in self._cache:
                logger.debug(f"Model '{model_name}' loaded from cache (after lock)")
                return self._cache[model_name]
            
            # Determine file path
            if file_path is None:
                file_path = self.models_dir / f"{model_name}.pkl"
            else:
                file_path = Path(file_path)
            
            # Load from disk
            logger.info(f"Loading model '{model_name}' from {file_path}")
            try:
                with open(file_path, "rb") as f:
                    model = pickle.load(f)
            except FileNotFoundError:
                logger.error(f"Model file not found: {file_path}")
                raise
            except pickle.UnpicklingError as e:
                logger.error(f"Failed to unpickle model '{model_name}': {e}")
                raise
            
            # Cache and return
            self._cache[model_name] = model
            logger.info(f"Model '{model_name}' loaded and cached")
            return model
    
    def clear_cache(self, model_name: Optional[str] = None):
        """Clear cache for specific model or all models.
        
        Args:
            model_name: Model to remove from cache. If None, clears entire cache.
        """
        with self._lock:
            if model_name:
                removed = self._cache.pop(model_name, None)
                if removed:
                    logger.info(f"Model '{model_name}' removed from cache")
                else:
                    logger.debug(f"Model '{model_name}' not in cache")
            else:
                count = len(self._cache)
                self._cache.clear()
                logger.info(f"Cache cleared ({count} models removed)")
    
    def get_cached_models(self) -> list[str]:
        """Get list of currently cached model names.
        
        Returns:
            List of model names present in cache
        """
        with self._lock:
            return list(self._cache.keys())


# Global singleton instance
_model_cache: Optional[ModelCache] = None
_cache_lock = threading.Lock()


def get_model_cache(models_dir: Optional[Path] = None) -> ModelCache:
    """Get or create the global ModelCache singleton.
    
    Thread-safe singleton initialization using double-checked locking.
    
    Args:
        models_dir: Directory containing model files. Required on first call,
                   ignored on subsequent calls (singleton already initialized).
    
    Returns:
        The global ModelCache instance
    
    Raises:
        ValueError: If called for first time without models_dir
    """
    global _model_cache
    
    # Fast path: return existing instance
    if _model_cache is not None:
        return _model_cache
    
    # Slow path: initialize singleton
    with _cache_lock:
        # Double-check: another thread might have initialized it
        if _model_cache is not None:
            return _model_cache
        
        if models_dir is None:
            # Try to get from settings
            try:
                from ..config import settings
                models_dir = Path(settings.models_dir)
            except (ImportError, AttributeError):
                raise ValueError(
                    "models_dir required for first call to get_model_cache(). "
                    "Either pass it explicitly or configure settings.models_dir"
                )
        
        _model_cache = ModelCache(models_dir)
        return _model_cache
