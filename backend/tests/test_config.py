"""Tests for configuration validation."""
import pytest
import os
from io import StringIO
from unittest.mock import patch
from pathlib import Path


def test_env_example_ships_placeholder_that_validator_rejects():
    """Verify .env.example contains an insecure placeholder that the validator will reject.
    
    This is intentional fail-fast design: the placeholder value forces developers
    to generate a proper salt before the app can start, preventing accidental
    deployment with insecure credentials.
    """
    env_example_path = Path(__file__).parent.parent / ".env.example"
    content = env_example_path.read_text()
    
    # The .env.example should contain the insecure placeholder
    assert "change-me-in-production-use-secrets-token-hex" in content


def test_insecure_salt_rejected():
    """Verify that insecure API_KEYS_SALT values are rejected on startup."""
    insecure_values = [
        "change-me-in-production-use-secrets-token-hex",
        "insecure-salt-change-me",
        "default",
        "secret",
        "salt",
    ]
    
    for insecure_value in insecure_values:
        with patch.dict(os.environ, {"API_KEYS_SALT": insecure_value}, clear=False):
            with patch("sys.stderr", new_callable=StringIO):
                with pytest.raises(SystemExit) as exc_info:
                    # Import fresh to trigger validation
                    import importlib
                    import app.config
                    importlib.reload(app.config)
                assert exc_info.value.code == 1


def test_short_salt_rejected():
    """Verify that short API_KEYS_SALT values are rejected on startup."""
    short_values = ["short", "a" * 31]  # Less than 32 characters
    
    for short_value in short_values:
        with patch.dict(os.environ, {"API_KEYS_SALT": short_value}, clear=False):
            with patch("sys.stderr", new_callable=StringIO):
                with pytest.raises(SystemExit) as exc_info:
                    # Import fresh to trigger validation
                    import importlib
                    import app.config
                    importlib.reload(app.config)
                assert exc_info.value.code == 1


def test_valid_salt_accepted():
    """Verify that a properly generated salt is accepted."""
    import secrets
    
    valid_salt = secrets.token_hex(32)  # 64 characters
    
    with patch.dict(os.environ, {"API_KEYS_SALT": valid_salt}, clear=False):
        # Import fresh to trigger validation
        import importlib
        import app.config
        importlib.reload(app.config)
        settings = app.config.settings
        assert settings.api_keys_salt == valid_salt
