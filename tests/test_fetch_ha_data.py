"""
Tests for fetch_ha_data.py error isolation.
"""

import json
import pytest
from unittest.mock import Mock, patch, mock_open
from datetime import datetime, timezone
import sys
import os

# Add parent directory to path to import fetch_ha_data
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fetch_ha_data


def test_fetch_history_isolates_json_decode_error():
    """fetch_history should return [] on malformed JSON, not crash."""
    mock_response = Mock()
    mock_response.json.side_effect = json.JSONDecodeError("Invalid", "", 0)
    mock_response.raise_for_status = Mock()
    
    with patch('fetch_ha_data.requests.get', return_value=mock_response):
        result = fetch_ha_data.fetch_history(
            "http://test.local:8123",
            "test_token",
            "sensor.test",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc)
        )
    
    assert result == []


def test_fetch_history_isolates_key_error():
    """fetch_history should handle missing keys in response gracefully."""
    mock_response = Mock()
    mock_response.json.return_value = {"unexpected": "structure"}
    mock_response.raise_for_status = Mock()
    
    with patch('fetch_ha_data.requests.get', return_value=mock_response):
        result = fetch_ha_data.fetch_history(
            "http://test.local:8123",
            "test_token",
            "sensor.test",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc)
        )
    
    assert result == []


def test_fetch_history_isolates_index_error():
    """fetch_history should handle empty array response."""
    mock_response = Mock()
    mock_response.json.return_value = []
    mock_response.raise_for_status = Mock()
    
    with patch('fetch_ha_data.requests.get', return_value=mock_response):
        result = fetch_ha_data.fetch_history(
            "http://test.local:8123",
            "test_token",
            "sensor.test",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc)
        )
    
    assert result == []


def test_fetch_history_isolates_type_error():
    """fetch_history should handle non-dict records."""
    mock_response = Mock()
    mock_response.json.return_value = [[None, "string", 123]]
    mock_response.raise_for_status = Mock()
    
    with patch('fetch_ha_data.requests.get', return_value=mock_response):
        result = fetch_ha_data.fetch_history(
            "http://test.local:8123",
            "test_token",
            "sensor.test",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc)
        )
    
    assert result == []


def test_main_succeeds_with_partial_data():
    """main() should succeed if at least one entity returns data."""
    mock_config = {"url": "http://test.local:8123", "token": "test_token"}
    
    # Entity 1 returns data, entity 2 fails
    def mock_fetch(url, token, entity_id, start, end):
        if entity_id == "sensor.good":
            return [
                {"entity_id": "sensor.good", "state": "25", "last_changed": "2026-01-01T12:00:00Z"}
            ]
        return []
    
    with patch('fetch_ha_data.load_ha_config', return_value=mock_config), \
         patch('fetch_ha_data.fetch_history', side_effect=mock_fetch), \
         patch('fetch_ha_data.export_to_csv') as mock_export, \
         patch('sys.argv', ['fetch_ha_data.py', '--entities', 'sensor.good', 'sensor.bad', 
                            '--output', 'test.csv', '--quiet']):
        
        exit_code = fetch_ha_data.main()
    
    assert exit_code == 0
    assert mock_export.called


def test_main_fails_only_if_all_entities_fail():
    """main() should fail only when ALL entities return no data."""
    mock_config = {"url": "http://test.local:8123", "token": "test_token"}
    
    with patch('fetch_ha_data.load_ha_config', return_value=mock_config), \
         patch('fetch_ha_data.fetch_history', return_value=[]), \
         patch('sys.argv', ['fetch_ha_data.py', '--entities', 'sensor.bad1', 'sensor.bad2', 
                            '--output', 'test.csv', '--quiet']):
        
        exit_code = fetch_ha_data.main()
    
    assert exit_code == 1


def test_fetch_history_returns_valid_data():
    """fetch_history should return records with entity_id added."""
    mock_response = Mock()
    mock_response.json.return_value = [[
        {"state": "25", "last_changed": "2026-01-01T12:00:00Z"}
    ]]
    mock_response.raise_for_status = Mock()
    
    with patch('fetch_ha_data.requests.get', return_value=mock_response):
        result = fetch_ha_data.fetch_history(
            "http://test.local:8123",
            "test_token",
            "sensor.temp",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc)
        )
    
    assert len(result) == 1
    assert result[0]["entity_id"] == "sensor.temp"
    assert result[0]["state"] == "25"
