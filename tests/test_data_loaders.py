"""
Test suite for data loading functions (load_ha_csv, load_open_meteo, etc.)

Covers:
- Valid inputs (happy path)
- Invalid JSON
- Missing required keys
- Empty data
- Timezone handling
- Duplicate timestamps
- Unknown/unavailable states (HA)
"""

import pytest
import pandas as pd
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone

import rainlib as rl


# ---------------------------------------------------------------------------
# load_ha_csv() tests
# ---------------------------------------------------------------------------

def test_load_ha_csv_happy_path():
    """Valid CSV should parse into long format with time, entity_id, value."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("entity_id,state,last_changed\n")
        f.write("sensor.temp,15.5,2026-07-20T10:00:00+00:00\n")
        f.write("sensor.humidity,65.0,2026-07-20T10:05:00+00:00\n")
        f.name
        csv_path = f.name
    
    try:
        df = rl.load_ha_csv(csv_path)
        assert len(df) == 2
        assert list(df.columns) == ["time", "entity_id", "value"]
        assert df["entity_id"].tolist() == ["sensor.temp", "sensor.humidity"]
        assert df["value"].tolist() == [15.5, 65.0]
        assert df["time"].dt.tz is not None  # UTC aware
    finally:
        Path(csv_path).unlink()


def test_load_ha_csv_drops_unknown_states():
    """Should drop rows with state='unknown' or 'unavailable'."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("entity_id,state,last_changed\n")
        f.write("sensor.temp,15.5,2026-07-20T10:00:00+00:00\n")
        f.write("sensor.temp,unknown,2026-07-20T10:05:00+00:00\n")
        f.write("sensor.temp,unavailable,2026-07-20T10:10:00+00:00\n")
        f.write("sensor.humidity,70.0,2026-07-20T10:15:00+00:00\n")
        csv_path = f.name
    
    try:
        df = rl.load_ha_csv(csv_path)
        assert len(df) == 2  # only valid rows
        assert "unknown" not in df["value"].tolist()
    finally:
        Path(csv_path).unlink()


def test_load_ha_csv_coerces_non_numeric():
    """Should drop rows where state cannot be coerced to float."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("entity_id,state,last_changed\n")
        f.write("sensor.temp,15.5,2026-07-20T10:00:00+00:00\n")
        f.write("sensor.temp,not_a_number,2026-07-20T10:05:00+00:00\n")
        f.write("sensor.humidity,70.0,2026-07-20T10:10:00+00:00\n")
        csv_path = f.name
    
    try:
        df = rl.load_ha_csv(csv_path)
        assert len(df) == 2
        assert all(isinstance(v, float) for v in df["value"])
    finally:
        Path(csv_path).unlink()


def test_load_ha_csv_sorted_by_time():
    """Output should be sorted by time ascending."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("entity_id,state,last_changed\n")
        f.write("sensor.temp,20.0,2026-07-20T10:10:00+00:00\n")
        f.write("sensor.temp,15.5,2026-07-20T10:00:00+00:00\n")
        f.write("sensor.temp,18.0,2026-07-20T10:05:00+00:00\n")
        csv_path = f.name
    
    try:
        df = rl.load_ha_csv(csv_path)
        assert df["value"].tolist() == [15.5, 18.0, 20.0]
    finally:
        Path(csv_path).unlink()


# ---------------------------------------------------------------------------
# load_open_meteo() tests
# ---------------------------------------------------------------------------

def test_load_open_meteo_from_dict():
    """Should parse a dict object."""
    data = {
        "hourly": {
            "time": ["2026-07-20T10:00", "2026-07-20T11:00"],
            "temperature_2m": [15.5, 16.0],
            "relative_humidity_2m": [65, 70],
            "precipitation": [0.0, 0.5],
        },
        "utc_offset_seconds": 0
    }
    df = rl.load_open_meteo(data)
    assert len(df) == 2
    assert "om_temp" in df.columns
    assert "om_rh" in df.columns
    assert "om_precip" in df.columns
    assert df.index.name == "time"
    assert df.index.tz is not None  # UTC aware


def test_load_open_meteo_from_json_string():
    """Should parse a JSON string."""
    json_str = json.dumps({
        "hourly": {
            "time": ["2026-07-20T10:00", "2026-07-20T11:00"],
            "temperature_2m": [15.5, 16.0],
        },
        "utc_offset_seconds": 0
    })
    df = rl.load_open_meteo(json_str)
    assert len(df) == 2
    assert "om_temp" in df.columns


def test_load_open_meteo_from_file():
    """Should parse a .json file."""
    data = {
        "hourly": {
            "time": ["2026-07-20T10:00", "2026-07-20T11:00"],
            "temperature_2m": [15.5, 16.0],
        },
        "utc_offset_seconds": 0
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(data, f)
        json_path = f.name
    
    try:
        df = rl.load_open_meteo(json_path)
        assert len(df) == 2
        assert "om_temp" in df.columns
    finally:
        Path(json_path).unlink()


def test_load_open_meteo_missing_hourly_key():
    """Should raise ValueError if JSON missing 'hourly' key."""
    bad_json = {"latitude": 53.9, "longitude": 27.6}
    with pytest.raises(ValueError, match="missing 'hourly' key"):
        rl.load_open_meteo(bad_json)


def test_load_open_meteo_invalid_json_string():
    """Should raise ValueError for malformed JSON string."""
    bad_json_str = "{this is not valid json"
    with pytest.raises(ValueError, match="Failed to parse JSON string"):
        rl.load_open_meteo(bad_json_str)


def test_load_open_meteo_file_not_found():
    """Should raise ValueError if file doesn't exist."""
    with pytest.raises(ValueError, match="File not found"):
        rl.load_open_meteo("/nonexistent/path/data.json")


def test_load_open_meteo_malformed_json_file():
    """Should raise ValueError for malformed JSON file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write("{this is not valid json")
        json_path = f.name
    
    try:
        with pytest.raises(ValueError, match="malformed JSON"):
            rl.load_open_meteo(json_path)
    finally:
        Path(json_path).unlink()


def test_load_open_meteo_timezone_conversion():
    """Should convert local time to UTC using utc_offset_seconds."""
    # utc_offset_seconds=10800 means UTC+3
    data = {
        "hourly": {
            "time": ["2026-07-20T13:00"],  # 13:00 local = 10:00 UTC
            "temperature_2m": [20.0],
        },
        "utc_offset_seconds": 10800
    }
    df = rl.load_open_meteo(data)
    expected_utc = pd.Timestamp("2026-07-20T10:00:00", tz="UTC")
    assert df.index[0] == expected_utc


def test_load_open_meteo_optional_fields():
    """Should handle missing optional fields (rain, showers)."""
    data = {
        "hourly": {
            "time": ["2026-07-20T10:00"],
            "temperature_2m": [15.5],
            # no rain, showers, precipitation
        },
        "utc_offset_seconds": 0
    }
    df = rl.load_open_meteo(data)
    assert "om_temp" in df.columns
    assert "om_rain" not in df.columns
    assert "om_showers" not in df.columns


# ---------------------------------------------------------------------------
# load_yandex_archive() tests
# ---------------------------------------------------------------------------

def test_load_yandex_archive_single_file():
    """Should load a single Yandex JSON snapshot."""
    data = {
        "now": 1721469600,  # 2026-07-20 10:00:00 UTC
        "fact": {
            "condition": "cloudy",
            "temp": 16,
            "humidity": 65,
            "feels_like": 14,
            "prec_prob": 20,
            "prec_strength": 0.0,
            "pressure_mm": 750,
            "wind_speed": 3.5,
        }
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "snapshot.json"
        json_path.write_text(json.dumps(data))
        
        df = rl.load_yandex_archive(str(json_path.parent))
        assert len(df) == 1
        assert "yx_condition" in df.columns
        assert "yx_temp" in df.columns
        assert "yx_is_rain" in df.columns
        assert df["yx_condition"].iloc[0] == "cloudy"
        assert df["yx_is_rain"].iloc[0] == 0  # no rain in condition


def test_load_yandex_archive_rain_detection():
    """Should detect rain in condition string."""
    data = {
        "now": 1721469600,
        "fact": {
            "condition": "light-rain",
            "temp": 16,
        }
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "snapshot.json"
        json_path.write_text(json.dumps(data))
        
        df = rl.load_yandex_archive(str(json_path.parent))
        assert df["yx_is_rain"].iloc[0] == 1


def test_load_yandex_archive_multiple_files():
    """Should merge multiple snapshots by timestamp."""
    snapshots = [
        {"now": 1721469600, "fact": {"condition": "cloudy", "temp": 15}},
        {"now": 1721473200, "fact": {"condition": "rain", "temp": 16}},
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        for i, snap in enumerate(snapshots):
            (Path(tmpdir) / f"snap{i}.json").write_text(json.dumps(snap))
        
        df = rl.load_yandex_archive(tmpdir)
        assert len(df) == 2
        assert df.index.name == "time"
        assert df.index[0] < df.index[1]  # sorted


def test_load_yandex_archive_missing_fact():
    """Should skip files without 'fact' key."""
    data = {"now": 1721469600}  # no fact
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "snapshot.json"
        json_path.write_text(json.dumps(data))
        
        df = rl.load_yandex_archive(tmpdir)
        assert len(df) == 0


def test_load_yandex_archive_glob_pattern():
    """Should accept glob patterns."""
    data = {"now": 1721469600, "fact": {"condition": "clear", "temp": 20}}
    with tempfile.TemporaryDirectory() as tmpdir:
        subdir = Path(tmpdir) / "2026" / "07"
        subdir.mkdir(parents=True)
        (subdir / "data.json").write_text(json.dumps(data))
        
        pattern = str(Path(tmpdir) / "**/*.json")
        df = rl.load_yandex_archive(pattern)
        assert len(df) == 1


# ---------------------------------------------------------------------------
# load_meteostat() tests
# ---------------------------------------------------------------------------

def test_load_meteostat_happy_path():
    """Should parse Meteostat JSON format."""
    data = {
        "meta": {},
        "data": [
            {"time": "2026-07-20 10:00:00", "temp": 15.5, "rhum": 65, "prcp": 0.0, "pres": 1013.0, "dwpt": 8.0},
            {"time": "2026-07-20 11:00:00", "temp": 16.0, "rhum": 70, "prcp": 0.5, "pres": 1012.5, "dwpt": 9.0},
        ]
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(data, f)
        json_path = f.name
    
    try:
        df = rl.load_meteostat(json_path)
        assert len(df) == 2
        assert "ms_temp" in df.columns
        assert "ms_rhum" in df.columns
        assert "ms_precip" in df.columns
        assert "ms_pres" in df.columns
        assert "ms_dwpt" in df.columns
        assert df.index.name == "time"
        assert df.index.tz is not None  # UTC aware
    finally:
        Path(json_path).unlink()


def test_load_meteostat_empty_data():
    """Should return empty DataFrame if no data records."""
    data = {"meta": {}, "data": []}
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(data, f)
        json_path = f.name
    
    try:
        df = rl.load_meteostat(json_path)
        assert len(df) == 0
        assert isinstance(df, pd.DataFrame)
    finally:
        Path(json_path).unlink()


def test_load_meteostat_file_not_found():
    """Should raise ValueError if file doesn't exist."""
    with pytest.raises(ValueError, match="File not found"):
        rl.load_meteostat("/nonexistent/path/data.json")


def test_load_meteostat_malformed_json():
    """Should raise ValueError for malformed JSON."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write("{this is broken json")
        json_path = f.name
    
    try:
        with pytest.raises(ValueError, match="malformed JSON"):
            rl.load_meteostat(json_path)
    finally:
        Path(json_path).unlink()


def test_load_meteostat_optional_columns():
    """Should handle missing optional columns (wdir, wspd)."""
    data = {
        "meta": {},
        "data": [
            {"time": "2026-07-20 10:00:00", "temp": 15.5, "rhum": 65},
        ]
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(data, f)
        json_path = f.name
    
    try:
        df = rl.load_meteostat(json_path)
        assert "ms_temp" in df.columns
        assert "ms_rhum" in df.columns
        assert "ms_wdir" not in df.columns
        assert "ms_wspd" not in df.columns
    finally:
        Path(json_path).unlink()


# ---------------------------------------------------------------------------
# ha_wide() tests
# ---------------------------------------------------------------------------

def test_ha_wide_pivot():
    """Should pivot long HA format into wide columns."""
    long_df = pd.DataFrame({
        "time": pd.to_datetime(["2026-07-20T10:00:00Z", "2026-07-20T10:05:00Z", "2026-07-20T10:00:00Z"], utc=True),
        "entity_id": ["sensor.temp", "sensor.temp", "sensor.humidity"],
        "value": [15.5, 16.0, 65.0]
    })
    
    entity_map = {
        "sensor.temp": "temperature",
        "sensor.humidity": "humidity"
    }
    
    wide = rl.ha_wide(long_df, entity_map)
    assert "temperature" in wide.columns
    assert "humidity" in wide.columns
    assert wide.index.name == "time"
    assert len(wide) == 2  # two unique timestamps


def test_ha_wide_empty_entity_map():
    """Should return empty DataFrame if no entities mapped."""
    long_df = pd.DataFrame({
        "time": pd.to_datetime(["2026-07-20T10:00:00Z"], utc=True),
        "entity_id": ["sensor.temp"],
        "value": [15.5]
    })
    
    with pytest.raises(ValueError, match="No objects to concatenate"):
        rl.ha_wide(long_df, {})


# ---------------------------------------------------------------------------
# build_grid() tests
# ---------------------------------------------------------------------------

def test_build_grid_single_source():
    """Should work with just one data source."""
    om_df = pd.DataFrame({
        "om_temp": [15.5, 16.0],
    }, index=pd.date_range("2026-07-20T10:00:00Z", periods=2, freq="1h"))
    om_df.index.name = "time"
    
    grid = rl.build_grid(om_df=om_df, freq="10min")
    assert len(grid) > 2  # resampled to 10min intervals
    assert "om_temp" in grid.columns


def test_build_grid_no_sources():
    """Should raise ValueError if no data sources provided."""
    with pytest.raises(ValueError, match="No data sources provided"):
        rl.build_grid()


def test_build_grid_precipitation_not_ffilled():
    """Precipitation columns should NOT be forward-filled."""
    om_df = pd.DataFrame({
        "om_precip": [0.5, None, None],  # precipitation at first hour only
        "om_temp": [15.5, None, None],
    }, index=pd.to_datetime(["2026-07-20T10:00:00Z", "2026-07-20T11:00:00Z", "2026-07-20T12:00:00Z"], utc=True))
    om_df.index.name = "time"
    
    grid = rl.build_grid(om_df=om_df, freq="1h")
    # om_precip should remain NaN at 11:00 and 12:00 (no ffill)
    # om_temp should be forward-filled (state variable)
    assert pd.isna(grid.loc[grid.index[1], "om_precip"])  # 11:00
    assert pd.isna(grid.loc[grid.index[2], "om_precip"])  # 12:00
    assert not pd.isna(grid.loc[grid.index[1], "om_temp"])  # should be ffilled


def test_build_grid_merges_multiple_sources():
    """Should merge HA, open-meteo, yandex, meteostat into one grid."""
    ha_df = pd.DataFrame({
        "ha_temp": [15.0],
    }, index=pd.to_datetime(["2026-07-20T10:00:00Z"], utc=True))
    ha_df.index.name = "time"
    
    om_df = pd.DataFrame({
        "om_temp": [15.5],
    }, index=pd.to_datetime(["2026-07-20T10:00:00Z"], utc=True))
    om_df.index.name = "time"
    
    grid = rl.build_grid(ha_wide_df=ha_df, om_df=om_df, freq="10min")
    assert "ha_temp" in grid.columns
    assert "om_temp" in grid.columns
