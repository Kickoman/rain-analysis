# Changelog

Notable changes to rain-analysis.

## 2026-07-18

### Fixed

- **Precipitation forward-fill removed** (`rainlib.py::build_grid()`). Previously, precipitation columns were forward-filled during grid construction, inflating rain-hour counts by approximately 80%. The fix restricts forward-fill to temperature/humidity/pressure columns only.
- See [DATA_SOURCES.md](DATA_SOURCES.md) for updated forward-fill behavior description.
