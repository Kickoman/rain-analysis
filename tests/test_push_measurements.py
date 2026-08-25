"""Tests for scripts_utils/push_measurements.py batching and payload building."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts_utils"))

from push_measurements import build_batches, post_batch, BATCH_SIZE


def test_build_batches_splits_at_batch_size():
    rows = [
        (f"sensor.a", str(i), f"2026-08-25T10:{i % 60:02d}:00+00:00")
        for i in range(BATCH_SIZE + 10)
    ]
    batches = list(build_batches(rows, source="test"))
    assert len(batches) == 2
    assert len(batches[0]["measurements"]) == BATCH_SIZE
    assert len(batches[1]["measurements"]) == 10
    assert batches[0]["source"] == "test"


def test_build_batches_filters_bad_rows():
    rows = [
        ("sensor.ok", "1.5", "2026-08-25T10:00:00+00:00"),
        ("sensor.no_ts", "1.5", ""),                      # no timestamp
        ("Sensor.BadName", "1.5", "2026-08-25T10:01:00+00:00"),  # invalid name
        ("sensor.none_state", None, "2026-08-25T10:02:00+00:00"),  # no state
    ]
    [batch] = list(build_batches(rows, source="test"))
    assert len(batch["measurements"]) == 1
    assert batch["measurements"][0] == {
        "sensor": "sensor.ok",
        "timestamp": "2026-08-25T10:00:00+00:00",
        "value": "1.5",
    }


def test_build_batches_stringifies_values():
    rows = [("sensor.n", 42.5, "2026-08-25T10:00:00+00:00")]
    [batch] = list(build_batches(rows, source="test"))
    assert batch["measurements"][0]["value"] == "42.5"


def test_post_batch_retries_on_5xx_then_succeeds():
    session = MagicMock()
    error_response = MagicMock(status_code=503, text="unavailable")
    ok_response = MagicMock(status_code=200)
    ok_response.json.return_value = {"accepted": 1, "created": 1, "updated": 0, "skipped_invalid": []}
    ok_response.raise_for_status.return_value = None
    session.post.side_effect = [error_response, ok_response]

    with patch("push_measurements.time.sleep"):
        result = post_batch(session, "http://x/api/v1/data/measurements", "key", {"measurements": []})

    assert result["created"] == 1
    assert session.post.call_count == 2


def test_post_batch_gives_up_after_max_retries():
    session = MagicMock()
    session.post.return_value = MagicMock(status_code=500, text="boom")

    with patch("push_measurements.time.sleep"):
        with pytest.raises(RuntimeError, match="after 3 attempts"):
            post_batch(session, "http://x/api/v1/data/measurements", "key", {"measurements": []})
