"""Tests for security-related configuration validation."""
import pytest
from pydantic import ValidationError
import os
import sys
from pathlib import Path


def test_api_keys_salt_rejects_default_value(monkeypatch):
    """Test that the insecure default value is rejected."""
    # Clear the cached settings module
    if 'app.config' in sys.modules:
        del sys.modules['app.config']
    
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("API_KEYS_SALT", "CHANGE_ME_GENERATE_SECURE_RANDOM_VALUE")
    
    with pytest.raises(ValidationError) as exc_info:
        from app.config import Settings
        Settings()
    
    assert "must be changed from default value" in str(exc_info.value)


def test_api_keys_salt_rejects_short_value(monkeypatch):
    """Test that salt values shorter than 32 characters are rejected."""
    if 'app.config' in sys.modules:
        del sys.modules['app.config']
    
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("API_KEYS_SALT", "tooshort")
    
    with pytest.raises(ValidationError) as exc_info:
        from app.config import Settings
        Settings()
    
    assert "must be at least 32 characters" in str(exc_info.value)


def test_api_keys_salt_accepts_secure_value(monkeypatch):
    """Test that a secure salt value is accepted."""
    if 'app.config' in sys.modules:
        del sys.modules['app.config']
    
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    # Generate a proper 64-character hex string (32 bytes)
    monkeypatch.setenv("API_KEYS_SALT", "a" * 64)
    
    from app.config import Settings
    settings = Settings()
    assert settings.api_keys_salt == "a" * 64


def test_api_keys_salt_accepts_32_character_minimum(monkeypatch):
    """Test that exactly 32 characters is accepted."""
    if 'app.config' in sys.modules:
        del sys.modules['app.config']
    
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("API_KEYS_SALT", "b" * 32)
    
    from app.config import Settings
    settings = Settings()
    assert settings.api_keys_salt == "b" * 32


def test_env_example_contains_expected_default():
    """Test that .env.example contains the expected default value that will be rejected."""
    env_example_path = os.path.join(
        os.path.dirname(__file__), "..", ".env.example"
    )
    with open(env_example_path) as f:
        content = f.read()
    
    # The .env.example should contain the obvious placeholder that triggers validation error
    assert "CHANGE_ME_GENERATE_SECURE_RANDOM_VALUE" in content
    # And should have instructions for generating a secure value
    assert "Generate" in content or "generate" in content
