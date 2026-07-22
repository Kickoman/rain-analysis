"""
tests/conftest.py — Pytest configuration for the rain-analysis test suite.

Adds the analysis/ and scripts_utils/ directories to sys.path so tests can
import modules from their new locations after Phase 1.1 restructuring.

Phase 1.1 restructured the project (issue #237):
  - ML modules → analysis/
  - Utility scripts → scripts_utils/
"""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
_analysis_dir = str(_project_root / "analysis")
_scripts_utils_dir = str(_project_root / "scripts_utils")

# Insert at front so these take priority over any other paths
for _dir in (_analysis_dir, _scripts_utils_dir):
    if _dir not in sys.path:
        sys.path.insert(0, _dir)
