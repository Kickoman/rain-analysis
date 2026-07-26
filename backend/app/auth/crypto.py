"""Cryptographic utilities for API key generation and validation."""

import secrets
import hashlib
from typing import Tuple


def generate_api_key(environment: str = "live") -> Tuple[str, str, str]:
    """
    Generate a new API key.
    
    Args:
        environment: "live" or "test"
    
    Returns:
        Tuple of (full_key, key_hash, key_prefix)
        - full_key: ra_live_<32 hex> or ra_test_<32 hex>
        - key_hash: SHA256 hash of full_key
        - key_prefix: first 10 chars for identification
    
    Raises:
        ValueError: If environment is not "live" or "test"
    """
    if environment not in ("live", "test"):
        raise ValueError("environment must be 'live' or 'test'")
    
    random_part = secrets.token_hex(16)  # 32 hex chars
    full_key = f"ra_{environment}_{random_part}"
    key_hash = hash_api_key(full_key)
    key_prefix = full_key[:10]  # ra_live_ab or ra_test_xy
    
    return full_key, key_hash, key_prefix


def hash_api_key(api_key: str) -> str:
    """
    Hash an API key using SHA256.
    
    Args:
        api_key: The API key to hash
    
    Returns:
        Hexadecimal string representation of the SHA256 hash
    """
    return hashlib.sha256(api_key.encode()).hexdigest()


def verify_api_key(provided_key: str, stored_hash: str) -> bool:
    """
    Verify that provided key matches stored hash.
    
    Uses constant-time comparison to prevent timing attacks.
    
    Args:
        provided_key: The API key provided by the client
        stored_hash: The stored hash to compare against
    
    Returns:
        True if the key matches the hash, False otherwise
    """
    computed_hash = hash_api_key(provided_key)
    return secrets.compare_digest(computed_hash, stored_hash)
