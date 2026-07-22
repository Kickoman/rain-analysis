#!/usr/bin/env python3
"""
Tests for fetch_openmeteo.py
"""

import sys
import subprocess
import pytest
from datetime import datetime, timezone


def test_forecast_mode_rejects_past_end_date():
    """Test that --use-forecast with --end != today fails with clear error."""
    
    result = subprocess.run(
        [
            sys.executable,
            "fetch_openmeteo.py",
            "--use-forecast",
            "--start", "2026-01-01",
            "--end", "2026-01-10",
            "--output", "/tmp/test_openmeteo.json"
        ],
        capture_output=True,
        text=True
    )
    
    assert result.returncode != 0, "Expected non-zero exit code for past --end date"
    assert "requires --end to be today" in result.stderr, \
        f"Expected error message about --end date, got: {result.stderr}"


def test_forecast_mode_accepts_today_end_date():
    """Test that --use-forecast with --end=today succeeds (or at least doesn't reject)."""
    
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # We can't actually fetch data in tests, but we can verify the validation passes
    # This test would need mocking to fully validate, but checking error handling is enough
    result = subprocess.run(
        [
            sys.executable,
            "fetch_openmeteo.py",
            "--use-forecast",
            "--start", today,
            "--end", today,
            "--output", "/tmp/test_openmeteo.json",
            "--quiet"
        ],
        capture_output=True,
        text=True,
        timeout=5
    )
    
    # Should not fail with "requires --end to be today" error
    assert "requires --end to be today" not in result.stderr, \
        f"Should not reject --end=today, got: {result.stderr}"


@pytest.mark.skip(reason="Makes real HTTP requests to Open-Meteo API, causing timeout in CI")
def test_forecast_mode_default_end_is_today():
    """Test that --use-forecast without --end defaults to today (no validation error)."""
    
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    result = subprocess.run(
        [
            sys.executable,
            "fetch_openmeteo.py",
            "--use-forecast",
            "--days", "3",
            "--output", "/tmp/test_openmeteo.json",
            "--quiet"
        ],
        capture_output=True,
        text=True,
        timeout=5
    )
    
    # Should not fail with date validation error
    assert "requires --end to be today" not in result.stderr, \
        f"Default --end should be today, got: {result.stderr}"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
