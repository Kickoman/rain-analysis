"""Tests for scripts_utils/pull_measurements.py paging and row conversion."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts_utils"))

from pull_measurements import iter_sensor_rows, normalise_timestamp


def _page(points, total):
    return {
        "series": [{"sensor": "sensor.a", "unit": "C", "type": "numeric",
                    "points": points}],
        "page": 1,
        "page_size": len(points),
        "total": total,
    }


def _session(pages):
    session = MagicMock()
    responses = []
    for payload in pages:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = payload
        responses.append(response)
    session.get.side_effect = responses
    return session


def test_pages_until_total_is_reached():
    first = _page([{"t": f"2026-08-25T0{i}:00:00Z", "v": float(i)} for i in range(3)], 5)
    second = _page([{"t": f"2026-08-25T0{i}:00:00Z", "v": float(i)} for i in (3, 4)], 5)
    session = _session([first, second])

    rows = list(iter_sensor_rows(session, "http://x/api/v1/data/measurements",
                                 "key", "sensor.a", None, None, 3))

    assert len(rows) == 5
    assert session.get.call_count == 2
    assert rows[0] == ("sensor.a", "0.0", "2026-08-25T00:00:00+00:00")


def test_one_sensor_per_request():
    session = _session([_page([{"t": "2026-08-25T00:00:00Z", "v": 1.0}], 1)])

    list(iter_sensor_rows(session, "http://x", "key", "sensor.a",
                          "2026-08-24T00:00:00+00:00", "2026-08-26T00:00:00+00:00", 5000))

    params = dict(session.get.call_args.kwargs["params"])
    assert params["sensor"] == "sensor.a"
    assert params["start"] == "2026-08-24T00:00:00+00:00"
    assert params["end"] == "2026-08-26T00:00:00+00:00"


def test_raw_is_used_when_value_failed_to_decode():
    page = _page([
        {"t": "2026-08-25T00:00:00Z", "v": None, "raw": "unavailable"},
        {"t": "2026-08-25T01:00:00Z", "v": None},
    ], 2)
    rows = list(iter_sensor_rows(_session([page]), "http://x", "key",
                                 "sensor.a", None, None, 5000))

    assert rows == [("sensor.a", "unavailable", "2026-08-25T00:00:00+00:00")]


def test_empty_page_stops_paging():
    empty = {"series": [], "page": 1, "page_size": 0, "total": 0}
    session = _session([empty])

    assert list(iter_sensor_rows(session, "http://x", "key",
                                 "sensor.a", None, None, 5000)) == []
    assert session.get.call_count == 1


def test_normalise_timestamp_matches_archive_format():
    assert normalise_timestamp("2026-08-16T04:15:06.125540Z") == \
        "2026-08-16T04:15:06.125540+00:00"
    assert normalise_timestamp("2026-08-16T07:15:06+03:00") == \
        "2026-08-16T04:15:06+00:00"
