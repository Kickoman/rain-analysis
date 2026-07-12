# Contributing Guide

Guidelines for developing and maintaining the rain-analysis project.

## Git Workflow

### Branching

- **Never commit directly to `master`**
- Create feature branches for all changes: `feat/feature-name`, `fix/bug-name`, `docs/update-name`
- One logical change per branch

### Commits

**Good commit messages:**
```
feat: add pressure-aware rain model

- Implements model_pressure_aware() in rainlib.py
- Uses 3h pressure derivative as primary signal
- Registers in MODELS for automatic scoring
- Tested: F1 0.67 (vs 0.35 baseline)
```

**Bad commit messages:**
```
update
fix stuff
wip
```

### Pull Requests

1. Create a feature branch
2. Make your changes
3. Commit with descriptive messages
4. Push to origin
5. Create PR via GitHub
6. Wait for review and approval
7. Merge with `--no-ff` (preserve history)

**PR titles:** `feat:`, `fix:`, `docs:`, `refactor:`, `test:`

**PR description should include:**
- What changed
- Why it changed
- How to test it
- Any breaking changes

## Code Style

### Python

- Follow PEP 8
- Use type hints for function signatures
- Docstrings for public functions (Google style)
- Keep functions focused (one thing well)

**Example:**
```python
def dew_point(temp_c: float, rh_pct: float) -> float:
    """Dew point (°C) from temperature and relative humidity.
    
    Uses Magnus-Tetens approximation with coefficients a=17.62, b=243.12.
    
    Args:
        temp_c: Temperature in Celsius
        rh_pct: Relative humidity in percent (0-100)
    
    Returns:
        Dew point in Celsius
    """
    # implementation
```

### Notebook

- Clear section headers (`## N. Section Name`)
- Markdown cells for explanations
- Keep code cells focused
- Show key results inline

## Testing Changes

### Before Committing

1. **Syntax check:**
   ```bash
   python -m py_compile your_file.py
   ```

2. **Import check:**
   ```bash
   python -c "import rainlib; import run_analysis"
   ```

3. **Run analysis on sample data:**
   ```bash
   python run_analysis.py --ha-csv data/sample.csv --output /tmp/test.json
   ```

### Adding a New Model

1. Implement in `rainlib.py`
2. Register in `MODELS`
3. Run notebook end-to-end
4. Run CLI script
5. Compare outputs (should match within rounding)

## Project Structure

### Core Files

- `rainlib.py` — **Single source of truth** for physics, models, metrics
- `rain_analysis.ipynb` — Interactive exploration
- `run_analysis.py` — Automated batch processing

**Critical:** Notebook and script must use the same `rainlib.py` functions.
Never duplicate logic between them.

### Adding Features

**Good:**
```python
# In rainlib.py
def new_feature(data):
    return result

# In notebook
grid['new'] = rl.new_feature(grid['data'])

# In run_analysis.py
grid['new'] = rl.new_feature(grid['data'])
```

**Bad:**
```python
# In notebook
grid['new'] = custom_logic_here()

# In run_analysis.py
grid['new'] = different_logic_here()  # ← divergence!
```

## Documentation

### When to Update Docs

- New script → new `docs/SCRIPT_NAME.md`
- New model → update `docs/BASELINE_MODEL.md` or create versioned doc
- CLI changes → update `docs/CLI_RUNNER.md`
- Data format changes → update relevant fetcher docs

### Doc Structure

```markdown
# Title

Brief overview (1-2 sentences).

## Quick Start

Minimal working example.

## Details

Comprehensive guide.

## Examples

Real-world use cases.

## Troubleshooting

Common issues and solutions.
```

## Data Management

### Never Commit Large Data

- Keep `data/` in `.gitignore`
- Sample files (< 100 KB) are OK in `data/` with clear `_sample` suffix
- Document where to get real data (URLs, scripts)

### Data Fetching Scripts

- `fetch_*.py` pattern for data acquisition
- Always include `--quiet` flag for automation
- Exit code 0 = success, non-zero = failure
- Write to stdout/stderr appropriately

## Versioning

### Model Versions

When the model changes significantly:
1. Document the old version: `docs/MODEL_v0.1.md`
2. Update baseline: `docs/BASELINE_MODEL.md` → current version
3. Tag in git: `git tag model-v0.2`

### Breaking Changes

If you change:
- CSV format expected by scripts
- JSON report structure
- Model parameter names

Then:
1. Increment version in relevant files
2. Update ALL documentation
3. Add migration notes

## Review Checklist

Before requesting PR review:

- [ ] Code follows style guide
- [ ] Tests pass (or sample run completes)
- [ ] Documentation updated
- [ ] Commit messages are clear
- [ ] No debugging code left in
- [ ] No secrets/tokens in code
- [ ] `.gitignore` updated if needed

## Questions?

Ask Kastuś (@karaziq) or open an issue in the repo.
