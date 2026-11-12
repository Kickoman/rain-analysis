"""Smoke test: the pipeline stage scripts resolve to real files (issue #452).

The repository has no tracked root entry points, so run_full_analysis.py
must resolve its sibling scripts relative to __file__ rather than the process
CWD. If a stage is missing, a clean clone fails on step 1/5 with
FileNotFoundError.
"""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_FULL_ANALYSIS = REPO_ROOT / "analysis" / "run_full_analysis.py"


def _load_run_full_analysis():
    spec = importlib.util.spec_from_file_location(
        "run_full_analysis", RUN_FULL_ANALYSIS
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pipeline_stage_scripts_exist():
    rfa = _load_run_full_analysis()
    assert rfa.ANALYSIS_DIR.is_dir()
    assert rfa.SCRIPTS_DIR.is_dir()
    for name, path in rfa.STAGE_SCRIPTS.items():
        assert path.is_file(), f"missing pipeline stage {name!r}: {path}"


def test_stage_script_paths_are_absolute():
    rfa = _load_run_full_analysis()
    for name, path in rfa.STAGE_SCRIPTS.items():
        assert path.is_absolute(), f"stage {name!r} must be absolute: {path}"
