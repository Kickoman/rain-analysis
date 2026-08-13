"""
Tests that the pressure models resolve regardless of sys.path.

`pressure_variants` lives in scripts_utils/ while rainlib lives in analysis/, and
rainlib used a bare `import pressure_variants`. That only works when something
else has already put scripts_utils/ on sys.path — the test suite's conftest does,
which is exactly why the gap stayed invisible here. In a plain run the five
pressure models are still advertised in MODELS but blow up when called, so the
failure lands mid-analysis instead of at import.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pandas as pd
import pytest

import rainlib as rl


PRESSURE_MODELS = [
    "pressure_absolute",
    "pressure_long_window",
    "pressure_lagged",
    "pressure_combined",
    "combined",
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _ctx(n=48):
    idx = pd.date_range("2026-07-01", periods=n, freq="1h", tz="UTC")
    return rl.ModelContext(
        spread=pd.Series(3.0, index=idx),
        spread_deriv=pd.Series(-0.5, index=idx),
        pressure=pd.Series(1010.0, index=idx),
        temp=pd.Series(18.0, index=idx),
        abs_humidity=pd.Series(12.0, index=idx),
    )


@pytest.mark.parametrize("name", PRESSURE_MODELS)
def test_registered_pressure_models_are_callable(name):
    assert name in rl.MODELS
    result = rl.MODELS[name](_ctx(), rl.ModelParams())
    assert len(result) == 48
    assert result.notna().any()


def test_every_registered_model_runs():
    """MODELS is the pipeline's contract — nothing in it may fail at call time."""
    for name, model in rl.MODELS.items():
        result = model(_ctx(), rl.ModelParams())
        assert len(result) == 48, name


def test_pressure_models_resolve_without_scripts_utils_on_path():
    """The real-world case: analysis/ importable, scripts_utils/ not."""
    script = textwrap.dedent("""
        import pandas as pd
        import rainlib as rl

        idx = pd.date_range("2026-07-01", periods=24, freq="1h", tz="UTC")
        ctx = rl.ModelContext(
            spread=pd.Series(3.0, index=idx),
            spread_deriv=pd.Series(-0.5, index=idx),
            pressure=pd.Series(1010.0, index=idx),
        )
        for name in %r:
            out = rl.MODELS[name](ctx, rl.ModelParams())
            assert len(out) == 24, name
        print("OK")
    """) % (PRESSURE_MODELS,)

    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env={"PYTHONPATH": str(PROJECT_ROOT / "analysis"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert "OK" in proc.stdout
