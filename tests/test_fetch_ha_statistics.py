"""
Tests for fetch_ha_statistics.py — long-term statistics export.

Long-term statistics are the only Home Assistant history that outlives the
recorder retention window, so these tests pin down the parts that decide
whether the export is usable: URL translation, timestamp parsing across HA
versions, and the CSV shape that rainlib.load_ha_csv() expects.
"""

import csv
import json
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

import fetch_ha_statistics as fhs


# ---------------------------------------------------------------------------
# WebSocket URL translation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("http_url,expected", [
    ("http://192.168.0.106:8123", "ws://192.168.0.106:8123/api/websocket"),
    ("http://192.168.0.106:8123/", "ws://192.168.0.106:8123/api/websocket"),
    ("https://ha.example.com", "wss://ha.example.com/api/websocket"),
    ("https://example.com/ha", "wss://example.com/ha/api/websocket"),
])
def test_websocket_url(http_url, expected):
    assert fhs.websocket_url(http_url) == expected


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

def test_stat_time_parses_epoch_millis():
    """Current HA returns `start` as epoch milliseconds."""
    ts = fhs._stat_time({"start": 1783879200000})
    assert ts == datetime.fromtimestamp(1783879200, tz=timezone.utc)
    assert ts.tzinfo is not None


def test_stat_time_parses_iso_string():
    """Older HA returns `start` as an ISO 8601 string."""
    assert fhs._stat_time({"start": "2026-07-01T15:00:00+00:00"}) == \
        datetime(2026, 7, 1, 15, 0, tzinfo=timezone.utc)


def test_stat_time_assumes_utc_for_naive_iso():
    """A naive timestamp must not become tz-naive downstream."""
    assert fhs._stat_time({"start": "2026-07-01T15:00:00"}).tzinfo is not None


# ---------------------------------------------------------------------------
# Flattening to HA-history records
# ---------------------------------------------------------------------------

def _result(entity="sensor.a", rows=None):
    return {entity: rows if rows is not None else []}


def test_to_records_selects_requested_statistic():
    result = _result(rows=[{"start": 1783879200000, "mean": 20.5, "min": 19.0, "max": 22.0}])

    assert fhs.to_records(result, "mean")[0]["state"] == 20.5
    assert fhs.to_records(result, "min")[0]["state"] == 19.0
    assert fhs.to_records(result, "max")[0]["state"] == 22.0


def test_to_records_skips_rows_missing_the_statistic():
    """A gap in the statistic must be dropped, not exported as None."""
    result = _result(rows=[
        {"start": 1783879200000, "mean": 20.5},
        {"start": 1783882800000, "mean": None},
        {"start": 1783886400000},
    ])

    assert len(fhs.to_records(result, "mean")) == 1


def test_to_records_sorted_by_time_then_entity():
    result = {
        "sensor.b": [{"start": 1783882800000, "mean": 2.0}],
        "sensor.a": [{"start": 1783882800000, "mean": 1.0},
                     {"start": 1783879200000, "mean": 0.0}],
    }

    records = fhs.to_records(result)
    assert [(r["entity_id"], r["state"]) for r in records] == [
        ("sensor.a", 0.0), ("sensor.a", 1.0), ("sensor.b", 2.0)
    ]


def test_to_records_emits_loadable_csv(tmp_path):
    """Output must match the entity_id,state,last_changed shape load_ha_csv reads."""
    import rainlib as rl

    result = _result("sensor.datchik_klimata_temperatura", [
        {"start": 1783879200000, "mean": 20.5},
        {"start": 1783882800000, "mean": 21.0},
    ])
    out = tmp_path / "stats.csv"
    fhs.export_to_csv(fhs.to_records(result), str(out))

    with open(out) as f:
        assert next(csv.reader(f)) == ["entity_id", "state", "last_changed"]

    loaded = rl.load_ha_csv(str(out))
    assert list(loaded.columns) == ["time", "entity_id", "value"]
    assert len(loaded) == 2
    assert loaded["value"].tolist() == [20.5, 21.0]
    assert loaded["time"].dt.tz is not None


# ---------------------------------------------------------------------------
# fetch_statistics — protocol handling
# ---------------------------------------------------------------------------

def _ws_mock(messages):
    ws = Mock()
    ws.recv = Mock(side_effect=[json.dumps(m) for m in messages])
    return ws


def test_fetch_statistics_returns_result():
    payload = {"sensor.a": [{"start": 1783879200000, "mean": 1.0}]}
    ws = _ws_mock([
        {"type": "auth_required"},
        {"type": "auth_ok"},
        {"id": 1, "type": "result", "success": True, "result": payload},
    ])

    with patch.object(fhs.websocket, "create_connection", return_value=ws):
        result = fhs.fetch_statistics(
            "http://ha.local:8123", "tok", ["sensor.a"],
            datetime(2026, 7, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 2, tzinfo=timezone.utc),
        )

    assert result == payload
    ws.close.assert_called_once()


def test_fetch_statistics_raises_on_auth_failure():
    ws = _ws_mock([
        {"type": "auth_required"},
        {"type": "auth_invalid", "message": "Invalid access token"},
    ])

    with patch.object(fhs.websocket, "create_connection", return_value=ws):
        with pytest.raises(RuntimeError, match="authentication failed"):
            fhs.fetch_statistics(
                "http://ha.local:8123", "tok", ["sensor.a"],
                datetime(2026, 7, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 2, tzinfo=timezone.utc),
            )

    ws.close.assert_called_once()


def test_fetch_statistics_raises_on_command_error():
    ws = _ws_mock([
        {"type": "auth_required"},
        {"type": "auth_ok"},
        {"id": 1, "type": "result", "success": False,
         "error": {"code": "invalid_format", "message": "bad period"}},
    ])

    with patch.object(fhs.websocket, "create_connection", return_value=ws):
        with pytest.raises(RuntimeError, match="bad period"):
            fhs.fetch_statistics(
                "http://ha.local:8123", "tok", ["sensor.a"],
                datetime(2026, 7, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 2, tzinfo=timezone.utc),
            )


def test_fetch_statistics_skips_unrelated_messages():
    """Events may arrive before the reply; the matching id must still be found."""
    payload = {"sensor.a": []}
    ws = _ws_mock([
        {"type": "auth_required"},
        {"type": "auth_ok"},
        {"id": 99, "type": "event"},
        {"id": 1, "type": "result", "success": True, "result": payload},
    ])

    with patch.object(fhs.websocket, "create_connection", return_value=ws):
        result = fhs.fetch_statistics(
            "http://ha.local:8123", "tok", ["sensor.a"],
            datetime(2026, 7, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 2, tzinfo=timezone.utc),
        )

    assert result == payload


def test_fetch_statistics_closes_socket_on_error():
    """A mid-protocol failure must not leak the connection."""
    ws = Mock()
    ws.recv = Mock(side_effect=OSError("connection reset"))

    with patch.object(fhs.websocket, "create_connection", return_value=ws):
        with pytest.raises(OSError):
            fhs.fetch_statistics(
                "http://ha.local:8123", "tok", ["sensor.a"],
                datetime(2026, 7, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 2, tzinfo=timezone.utc),
            )

    ws.close.assert_called_once()


def test_rain_probability_not_in_defaults():
    """It has no state_class, so it has no statistics — fetching it would mislead."""
    assert "sensor.rain_probability" not in fhs.DEFAULT_ENTITIES
