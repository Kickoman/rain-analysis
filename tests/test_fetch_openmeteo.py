#!/usr/bin/env python3
"""
Tests for fetch_openmeteo.py
"""

import sys
import subprocess
import pytest
from datetime import datetime, timezone
from pathlib import Path


# Resolve path to fetch_openmeteo.py in scripts_utils/
_project_root = Path(__file__).resolve().parent.parent
_fetch_openmeteo = str(_project_root / "scripts_utils" / "fetch_openmeteo.py")


def test_forecast_mode_rejects_past_end_date():
    """Test that --use-forecast with --end != today fails with clear error."""
    
    result = subprocess.run(
        [
            sys.executable,
            _fetch_openmeteo,
            "--use-forecast",
            "--start", "2026-01-01",
            "--end", "2026-01-10",
            "--output", "/tmp/test_openmeteo.json",
            "--dry-run"
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
    
    result = subprocess.run(
        [
            sys.executable,
            _fetch_openmeteo,
            "--use-forecast",
            "--start", today,
            "--end", today,
            "--output", "/tmp/test_openmeteo.json",
            "--dry-run",
            "--quiet"
        ],
        capture_output=True,
        text=True,
        timeout=5
    )
    
    # Should not fail with "requires --end to be today" error
    assert "requires --end to be today" not in result.stderr, \
        f"Should not reject --end=today, got: {result.stderr}"
    
    # Should succeed with dry-run
    assert result.returncode == 0, \
        f"Expected success with --dry-run, got code {result.returncode}: {result.stderr}"


def test_forecast_mode_default_end_is_today():
    """Test that --use-forecast without --end defaults to today (no validation error)."""
    
    result = subprocess.run(
        [
            sys.executable,
            _fetch_openmeteo,
            "--use-forecast",
            "--days", "3",
            "--output", "/tmp/test_openmeteo.json",
            "--dry-run",
            "--quiet"
        ],
        capture_output=True,
        text=True,
        timeout=5
    )
    
    # Should not fail with date validation error
    assert "requires --end to be today" not in result.stderr, \
        f"Default --end should be today, got: {result.stderr}"
    
    # Should succeed with dry-run
    assert result.returncode == 0, \
        f"Expected success with --dry-run, got code {result.returncode}: {result.stderr}"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
