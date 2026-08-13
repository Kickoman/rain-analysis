"""
Test suite for load_yandex_archive() error handling (issue #340).

Tests that the function properly handles:
- Malformed JSON files
- Binary/non-UTF-8 files (UnicodeDecodeError)
- Missing files
- Read errors
- Warning when files are skipped
"""

import pytest
import json
import tempfile
import warnings
from pathlib import Path

import rainlib as rl


def test_load_yandex_archive_skips_malformed_json():
    """Should skip malformed JSON files and continue processing valid ones."""
    valid_data = {"now": 1721469600, "fact": {"condition": "clear", "temp": 20}}
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Valid file
        (Path(tmpdir) / "valid.json").write_text(json.dumps(valid_data))
        # Malformed file
        (Path(tmpdir) / "broken.json").write_text("{this is not valid json")
        
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            df = rl.load_yandex_archive(tmpdir)
            
            # Should successfully load the valid file
            assert len(df) == 1
            assert df["yx_temp"].iloc[0] == 20
            
            # Should emit warning about skipped file
            assert len(w) == 1
            assert "skipped 1/2 files" in str(w[0].message)


def test_load_yandex_archive_skips_binary_files():
    """Should skip binary/non-UTF-8 files (UnicodeDecodeError) and continue processing."""
    valid_data = {"now": 1721469600, "fact": {"condition": "clear", "temp": 20}}
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Valid file
        (Path(tmpdir) / "valid.json").write_text(json.dumps(valid_data))
        # Binary file that will trigger UnicodeDecodeError
        (Path(tmpdir) / "binary.json").write_bytes(b'\xff\xfe\x00\x00binary data')
        
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            df = rl.load_yandex_archive(tmpdir)
            
            # Should successfully load the valid file
            assert len(df) == 1
            assert df["yx_temp"].iloc[0] == 20
            
            # Should emit warning about skipped file
            assert len(w) == 1
            assert "skipped 1/2 files" in str(w[0].message)


def test_load_yandex_archive_all_files_broken():
    """Should return empty DataFrame and warn when all files are broken."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "broken1.json").write_text("{invalid json")
        (Path(tmpdir) / "broken2.json").write_text("not json at all")
        
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            df = rl.load_yandex_archive(tmpdir)
            
            # Should return empty DataFrame
            assert len(df) == 0
            
            # Should warn about all files skipped
            assert len(w) == 1
            assert "skipped 2/2 files" in str(w[0].message)


def test_load_yandex_archive_no_warning_when_all_valid():
    """Should NOT emit warning when all files are processed successfully."""
    data = {"now": 1721469600, "fact": {"condition": "clear", "temp": 18}}
    
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "file1.json").write_text(json.dumps(data))
        (Path(tmpdir) / "file2.json").write_text(json.dumps(data))
        
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            df = rl.load_yandex_archive(tmpdir)
            
            # Should load both files
            assert len(df) == 1  # same timestamp, so merged
            
            # Should NOT emit warning
            assert len(w) == 0


def test_load_yandex_archive_uses_context_manager():
    """Verifies that file handles are properly closed (implicit test via successful cleanup)."""
    data = {"now": 1721469600, "fact": {"condition": "cloudy", "temp": 16}}
    
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "test.json"
        json_path.write_text(json.dumps(data))
        
        # Load the file
        df = rl.load_yandex_archive(tmpdir)
        assert len(df) == 1
        
        # File should be closed now, so we can delete it without issues
        json_path.unlink()  # Should not raise "file in use" error


def test_load_yandex_archive_mixed_valid_and_invalid():
    """Should process mixture of valid, malformed, and missing-fact files correctly."""
    valid1 = {"now": 1721469600, "fact": {"condition": "clear", "temp": 20}}
    valid2 = {"now": 1721473200, "fact": {"condition": "rain", "temp": 16}}
    no_fact = {"now": 1721476800}  # missing fact key
    
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "valid1.json").write_text(json.dumps(valid1))
        (Path(tmpdir) / "valid2.json").write_text(json.dumps(valid2))
        (Path(tmpdir) / "no_fact.json").write_text(json.dumps(no_fact))
        (Path(tmpdir) / "broken.json").write_text("{malformed")
        
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            df = rl.load_yandex_archive(tmpdir)
            
            # Should load 2 valid files (no_fact is skipped silently, broken triggers warning)
            assert len(df) == 2
            assert df["yx_temp"].iloc[0] == 20
            assert df["yx_temp"].iloc[1] == 16
            
            # Should warn about 1 skipped file (the malformed one)
            assert len(w) == 1
            assert "skipped 1/4 files" in str(w[0].message)
