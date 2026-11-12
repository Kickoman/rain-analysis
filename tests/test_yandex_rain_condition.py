"""Tests for Yandex rain-condition classification (issue #454).

Before the fix, `yx_is_rain` matched only the substring "rain", so
`drizzle`, `showers` and bare `thunderstorm` snapshots were counted as dry,
while `cross_check()` used a different (also wrong) list. A single shared
predicate `is_rain_condition()` / `YX_RAIN_CONDITIONS` now drives both.

The classification decision:
  - rain = liquid precipitation or a thunderstorm (convective rain event)
  - NOT rain = frozen/mixed precipitation (hail, wet-snow, snow) and dry codes
"""

import json
import tempfile
from pathlib import Path

import pytest

import rainlib as rl


# Every Yandex condition code and whether it means rain.
ALL_CONDITIONS = [
    # dry
    ("clear", False),
    ("partly-cloudy", False),
    ("cloudy", False),
    ("overcast", False),
    # liquid precipitation
    ("drizzle", True),
    ("light-rain", True),
    ("rain", True),
    ("heavy-rain", True),
    ("showers", True),
    # frozen / mixed
    ("wet-snow", False),
    ("light-snow", False),
    ("snow", False),
    ("snow-showers", False),
    ("hail", False),
    # thunderstorm family
    ("thunderstorm", True),
    ("thunderstorm-with-rain", True),
    ("thunderstorm-with-hail", True),
]


@pytest.mark.parametrize("condition,expected", ALL_CONDITIONS)
def test_is_rain_condition(condition, expected):
    assert rl.is_rain_condition(condition) is expected


@pytest.mark.parametrize("condition,expected", ALL_CONDITIONS)
def test_load_yandex_archive_yx_is_rain(condition, expected):
    """load_yandex_archive must use the shared predicate for yx_is_rain."""
    data = {"now": 1721469600, "fact": {"condition": condition, "temp": 16}}
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "s.json").write_text(json.dumps(data))
        df = rl.load_yandex_archive(tmpdir)
        assert df["yx_is_rain"].iloc[0] == (1 if expected else 0)


def test_is_rain_condition_non_string():
    assert rl.is_rain_condition(None) is False
    assert rl.is_rain_condition("") is False
    assert rl.is_rain_condition(123) is False


def test_yx_rain_conditions_matches_documented_set():
    """The shared set covers exactly the documented rain codes."""
    assert rl.YX_RAIN_CONDITIONS == {
        "drizzle", "light-rain", "rain", "heavy-rain", "showers",
        "thunderstorm", "thunderstorm-with-rain", "thunderstorm-with-hail",
    }
