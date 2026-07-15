# GitHub Pages for Rain Analysis

This branch contains the auto-generated GitHub Pages site for the rain-analysis project.

**DO NOT EDIT FILES HERE MANUALLY** — they are auto-generated from the master branch.

## Structure

- `index.html` — Main landing page
- `current/` — Latest analysis report
- `history/` — Historical reports archive
- `metrics/` — Performance metrics timeline
- `assets/` — CSS and other static assets
- `scripts/` — Build scripts (copied from master)

## Automation

The site is automatically updated via GitHub Actions workflow when:
- New reports are pushed to `master` branch in `reports/` directory
- Manual workflow dispatch is triggered

See `.github/workflows/deploy-pages.yml` in master branch for details.

## Local Development

To preview locally:

```bash
python -m http.server 8000
# Visit http://localhost:8000
```

To regenerate pages manually:

```bash
git checkout master
python scripts/md_to_html.py reports/2026-07-15.md current/index.html
```
