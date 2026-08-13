"""
Tests for the sensor diagnostics section.

Models are scored on the raw balcony sensor because that is what production
reads. These diagnostics keep the sensor's own error visible separately, so a
weak model score is not mistaken for a calibration fault or the reverse — and
so a replica that has drifted away from the deployed sensor is caught rather
than silently ranked against the other models.
"""

from datetime import timezone

import numpy as np
import pandas as pd
import pytest

from daily_analysis import (REPLICA_MAX_MAE, generate_sensor_diagnostics)
from run_analysis import _agreement, sensor_diagnostics


def frame(n=48, **cols):
    """Grid fixture. Scalars become a gently varying series, since correlation
    is undefined for a constant one."""
    idx = pd.date_range("2026-08-01", periods=n, freq="1h", tz="UTC")
    ramp = np.linspace(0.0, 1.0, n)
    return pd.DataFrame(
        {k: (np.asarray(v, dtype=float) if not np.isscalar(v) else float(v) + ramp)
         for k, v in cols.items()},
        index=idx,
    )


# ---------------------------------------------------------------------------
# _agreement
# ---------------------------------------------------------------------------

def test_agreement_on_identical_series():
    s = pd.Series([1.0, 2.0, 3.0, 4.0])
    result = _agreement(s, s)
    assert result["corr"] == pytest.approx(1.0)
    assert result["bias"] == pytest.approx(0.0)
    assert result["mae"] == pytest.approx(0.0)


def test_agreement_reports_signed_bias():
    a = pd.Series([11.0, 12.0, 13.0])
    b = pd.Series([10.0, 11.0, 12.0])
    assert _agreement(a, b)["bias"] == pytest.approx(1.0)
    assert _agreement(b, a)["bias"] == pytest.approx(-1.0)


def test_agreement_separates_bias_from_mae():
    """A pure offset has |bias| == MAE; scatter pushes MAE above |bias|."""
    a = pd.Series([10.0, 12.0, 14.0])
    b = pd.Series([11.0, 11.0, 15.0])
    result = _agreement(a, b)
    assert abs(result["bias"]) < result["mae"]


def test_agreement_ignores_unpaired_samples():
    a = pd.Series([1.0, 2.0, np.nan, 4.0])
    b = pd.Series([1.0, np.nan, 3.0, 4.0])
    assert _agreement(a, b)["n"] == 2


def test_agreement_needs_two_points():
    assert _agreement(pd.Series([1.0]), pd.Series([1.0])) is None
    assert _agreement(pd.Series([], dtype=float), pd.Series([], dtype=float)) is None


# ---------------------------------------------------------------------------
# sensor_diagnostics
# ---------------------------------------------------------------------------

def test_reports_configured_comparisons():
    grid = frame(temp=20.0, rh=60.0, pressure=1000.0,
                 om_temp=19.0, om_rh=65.0, om_pressure=999.0,
                 ms_temp=18.5, ms_rhum=66.0)

    comparisons = sensor_diagnostics(grid)["reference_comparisons"]

    assert "temp_vs_open_meteo" in comparisons
    assert "rh_vs_meteostat" in comparisons
    assert "pressure_vs_open_meteo" in comparisons


def test_pressure_is_not_compared_against_sea_level_reduced_data():
    """Meteostat `pres` is reduced to sea level; the local barometer is not.

    Differencing them reports Minsk's ~220 m elevation as a ~26 hPa bias, which
    reads as a broken sensor. Only the station-level reference is used.
    """
    grid = frame(pressure=999.0, ms_pres=1025.0, om_pressure=998.0)

    comparisons = sensor_diagnostics(grid)["reference_comparisons"]

    assert "pressure_vs_meteostat" not in comparisons
    assert comparisons["pressure_vs_open_meteo"]["bias"] == pytest.approx(1.0, abs=0.1)


def test_missing_references_are_omitted_not_zeroed():
    grid = frame(temp=20.0, rh=60.0)

    assert sensor_diagnostics(grid)["reference_comparisons"] == {}


def test_replica_agreement_is_reported():
    grid = frame(model_ha_live=[float(i % 40) for i in range(48)],
                 ha_rain_prob=[float(i % 40) for i in range(48)])

    replica = sensor_diagnostics(grid)["replica_vs_actual"]
    assert replica["corr"] == pytest.approx(1.0)
    assert replica["mae"] == pytest.approx(0.0)


def test_replica_is_none_without_the_production_sensor():
    """Beyond the recorder window sensor.rain_probability simply does not exist."""
    grid = frame(model_ha_live=50.0)
    assert sensor_diagnostics(grid)["replica_vs_actual"] is None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _report(comparisons=None, replica=None):
    return {"cross_check": {"sensor_diagnostics": {
        "reference_comparisons": comparisons or {},
        "replica_vs_actual": replica,
    }}}


def test_render_includes_each_comparison():
    text = generate_sensor_diagnostics(_report(
        {"temp_vs_open_meteo": {"n": 235, "corr": 0.912, "bias": 1.63, "mae": 1.91}}))

    assert "Sensor Diagnostics" in text
    assert "temp vs open meteo" in text
    assert "+1.63" in text


def test_render_warns_when_replica_has_drifted():
    text = generate_sensor_diagnostics(_report(
        replica={"n": 200, "corr": 0.809, "bias": -0.7, "mae": REPLICA_MAX_MAE + 4.4}))

    assert "WARNING" in text
    assert "do not describe the deployed model" in text


def test_render_is_quiet_when_replica_matches():
    text = generate_sensor_diagnostics(_report(
        replica={"n": 201, "corr": 0.998, "bias": 0.04, "mae": 0.19}))

    assert "WARNING" not in text
    assert "corr 0.998" in text


def test_render_explains_a_missing_production_sensor():
    text = generate_sensor_diagnostics(_report({"x": {"n": 2, "corr": 1.0, "bias": 0.0, "mae": 0.0}}))
    assert "no long-term statistics" in text


def test_render_empty_when_diagnostics_absent():
    assert generate_sensor_diagnostics({"cross_check": {}}) == ""
