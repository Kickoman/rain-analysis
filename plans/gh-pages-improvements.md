# GitHub Pages pipeline — audit and improvement plan

_Audit date: 2026-08-13. Audited against `master` @ `3a7eea8` and `origin/gh-pages` @ `42f4118`._

## Status — implemented 2026-08-14

Stages 1–3 are done in full; stages 4–5 are done except for the items listed as
deferred below. The suite is at 488 passing tests, and all 323 internal links in
a locally generated site resolve.

| Stage | Items | Status |
|---|---|---|
| 1 — Stop publishing wrong numbers | B1, B2, B3, B4 | ✅ done |
| 2 — Make failure visible | F1, F2, F3, F4 | ✅ done |
| 3 — Publish the documents that matter | B5, B6, B7 | ✅ done |
| 4 — Shared shell and converter | Q3, Q4, Q6, Q7, M3, F8 | ✅ mostly — see deferred |
| 5 — Hygiene and capability | Q1, F5, F6, F9, M4, M5 | ✅ mostly — see deferred |

New files: `scripts_utils/report_parse.py` (the single leaderboard parser),
`scripts_utils/check_site.py` (the pre-publish gate), `scripts_utils/markdown_lite.py`
(lists, italics, rules), `scripts_utils/page_head.py`, `site/assets/style.css`,
`site/404.html`, plus tests for each.

One defect was found during implementation and is not in the audit above:
publishing every document exposed their cross-references — `[MODELS.md](MODELS.md)`
resolves on GitHub and 404s on the site. `convert_docs_to_html.py` now rewrites
relative sibling `*.md` links to the generated `.html`.

**Deferred, with reasons:**

- **Item 14, the full `page_shell.py` refactor.** The `<head>` furniture is now
  shared (`page_head.py`) and the nav is consistent across all six generators,
  which is what the missing-Glossary-link and no-favicon findings actually
  needed. Each generator still builds its own `<header>`/`<nav>`/`<footer>`
  string. Mechanical, low risk, no user-visible payoff — worth doing next time
  one of them is touched.
- **Item 15, folding `convert_docs_to_html.py` into `md_to_html.py`.** The
  duplicated *markdown* logic is now shared via `markdown_lite.py` and the dead
  `convert_glossary_to_html.py` is deleted. Merging the two entry points behind
  a `--style` flag is cosmetic once the logic is shared.
- **Dark mode** (part of item 16). Not attempted: it cannot be verified from
  here, and shipping an unreviewed palette is worse than not having one.
- **`--output-dir` arguments** (part of item 20). The build artifacts are
  removed from `master` and `.gitignore`d, so running a generator from the repo
  root no longer pollutes the tree — which was the actual harm.
- **Item 23 nice-to-haves** — `workflow_dispatch` dry-run, an RSS feed, a
  failure notification. A link check was run manually against the generated
  tree (323 links, all resolving) but is not yet a workflow step.
- **Two `<h1>`s per report page**, `<noscript>`, `robots.txt`, `sitemap.xml`
  (part of Q5). Untouched.

---

## Context

The site at `https://kickoman.github.io/rain-analysis` is published from a long-lived
`gh-pages` branch rather than from an artifact upload. `.github/workflows/deploy-pages.yml`
checks out `master`, then `git checkout gh-pages`, then pulls a handful of paths back out of
`master` with `git checkout master -- <path>` (five generator scripts, `reports/20*.md`,
`reports/pressure_variants_*.md`, `docs_site/GLOSSARY.md`). It converts each report to
`history/<date>.html`, copies the newest daily report to `current/index.html`, converts
`GLOSSARY.md` to `docs/GLOSSARY.html`, then runs three generators that *re-scrape the HTML it
just produced* to build `history/index.html`, `index.html` and `metrics/index.html` +
`metrics/data.json`. Finally it deletes the scripts and reports from the working tree,
`git add .`, commits and pushes. `history/*.html` is never pruned, so it accumulates.

That "generate HTML, then regex the HTML back into structured data" round-trip is the
architectural weak point, and it is the reason this audit was commissioned: the 2026-08-13
analysis-pipeline fix (`docs_site/CHANGELOG.md`) changed the daily report format — new
"Source data ranges", "Sensor Diagnostics" and ground-truth-agreement sections, and, crucially,
models with no scored samples now render `N/A` / `⚪ no data` instead of `0.000`. Every parser in
the publishing pipeline matches numeric cells with `[0-9.]+`, so `N/A` is not a parse failure to
them — it is simply *no match*, and every one of them responds to "no match" by looking somewhere
else in the document instead of stopping.

The whole suite passes (`406 passed in 8.02s`) and the pipeline runs to completion on today's
report, so nothing here shows up as a red build. The damage is silent.

---

## Findings

### BROKEN

#### B1. `_extract_model_rows` falls through to the *Temporal Metrics* table and publishes those numbers as plain F1/precision/recall

`scripts_utils/generate_metrics_page.py:58-81`. The docstring says "from the FIRST matching table
only", and the comment on line 67-68 repeats it, but the implementation does something else:

```python
tables = html_content.split('</table>')
for table_html in tables:          # <-- iterates EVERY table
    rows = []
    for m in pat.finditer(table_html):
        rows.append(...)
    if rows:
        return rows                # <-- first table that yields ANY match wins
return []
```

If the leaderboard yields no matches, the loop keeps going and returns the *next* table's rows.
Before 2026-08-13 the leaderboard always contained numbers, so this could not fire. Now it can:
a day on which no model has scored samples (ground-truth fetch failure — the changelog notes the
Meteostat 30-day error used to be swallowed exactly this way) renders an all-`N/A` leaderboard,
and the parser silently moves on to **Temporal Metrics**, which is a completely different
measurement: F1 under a ±3h/±1h prediction-window tolerance, at a per-model tuned threshold,
with three rows per model (7d/14d/28d).

Evidence — I copied `history/2026-08-13.html`, blanked every numeric cell in the first table
only, and re-ran the generator:

```
rows parsed from a fully-N/A leaderboard: 30      (expected: 0)
   {'model': 'combined', 'f1': 0.444, ...}        7d  temporal
   {'model': 'combined', 'f1': 0.452, ...}        14d temporal
   {'model': 'combined', 'f1': 0.553, ...}        28d temporal
published series value for 2026-08-14:
  combined   f1=0.553 prec=0.513 rec=0.6
  tuned      f1=0.527 prec=0.514 rec=0.54
  original   f1=0.508 prec=0.515 rec=0.5
```

The generator exits `0`, prints `✅ Generated metrics/index.html — 33 reports`, and the workflow
publishes. Because each model matches three times and `series[-1] = r.get(metric)`
(`generate_metrics_page.py:169`) overwrites, the **28-day** value is the one that survives — so
the chart would show every model roughly doubling overnight (0.27 → 0.55) with no warning
anywhere. This is the worst finding in the audit: it manufactures plausible-looking data.

**Fix:** anchor the leaderboard by its heading (`## Model Performance (N-day window)`) instead of
"first table that matches"; make `N/A` an explicit token that parses to `None` rather than a
non-match; and if the anchored table yields zero rows, record the file as skipped rather than
searching elsewhere.

#### B2. Same fall-through in `_extract_f1_from_leaderboard`, now reachable via `ha_live_actual`

`scripts_utils/generate_history_index.py:44-66`. Identical shape — the docstring (lines 46-50)
says "Searches only within the FIRST `<table>`", the loop searches all of them. The existing test
`tests/test_generate_history_index.py:25-48` only covers the case where the model *is* in the
first table, so it passes without exercising the fall-through at all.

Evidence — synthetic report where the best model is `N/A` in the leaderboard and `0.500` in
Temporal Metrics:

```
A1 history-index  _extract_best_model  -> ha_live_actual (F1: 0.500)
```

`0.500` is the temporal-tolerance F1. The history card would present it as the leaderboard F1.
`ha_live_actual` is exactly the model that is `N/A` in today's report
(`reports/2026-08-13.md:46`), and it is the production model — the one most likely to be "best"
once its data returns.

**Fix:** stop after the first table that *contains the model name at all*; return `None` when its
metric cell is `N/A`.

#### B3. Landing page reads the wrong F1 — no `<td>` anchor, no table isolation

`scripts_utils/generate_landing_page.py:60-65`:

```python
f1_m = re.search(rf'{re.escape(m.group(1))}</td>\s*<td>([0-9.]+)', html)
```

Two defects at once. There is no `<td>` before the model name, so any model whose name is a
*suffix* of another matches the wrong row; and the search is unanchored over the whole document,
so on an `N/A` leaderboard it walks forward into later tables (same as B1/B2).

Evidence — both proved against the live code:

```
A2 landing-page  best_f1 for 'ha_live_actual' -> 0.500   (leaderboard cell is N/A; 0.500 is temporal)
B1 landing-page  best_f1 for 'combined'       -> 0.111   (matched pressure_combined; true value 0.999)
```

The `combined` / `pressure_combined` collision is live today: both models exist
(`reports/2026-08-13.md:45,51`). It happens not to fire only because the leaderboard is sorted
alphabetically and `combined` precedes `pressure_combined`; the "Model F1 under each ground truth"
table (`reports/2026-08-13.md:217-228`) is sorted by rank and *does* put `pressure_combined`
first. One sort-order change in `daily_analysis.py` and the homepage headline number is wrong.

**Fix:** reuse the already-correct pattern from `generate_history_index.py:57-61`, which anchors
with `<tr>\s*<td>{name}</td>`. Do not write a third copy — see M1.

#### B4. `ha_live_actual` silently disappears from the site

Three separate parsers drop it, none of them says anything:

| Consumer | Location | Behaviour on an `N/A` row |
|---|---|---|
| metrics series | `generate_metrics_page.py:60-66` | row not matched → model absent from that day |
| landing model list | `generate_landing_page.py:83` | `([0-9.]+)` fails → model absent from "Current Models" |
| history card F1 | `generate_history_index.py:57-61` | falls through (B2) |

Evidence — the currently published page still lists it, the next deploy will not:

```
$ git show origin/gh-pages:index.html | sed -n '/Current Models/,/<\/ul>/p'
    <li><strong>ha_live_actual</strong> — ✅ Production — actual HA sensor (F1=0.484)</li>   ← present today

$ python scripts_utils/generate_landing_page.py   # against reports/2026-08-13.md
models_in_report: ['combined', 'ha_live_replica', 'original', 'pressure_absolute',
                   'pressure_aware', 'pressure_combined', 'pressure_lagged',
                   'pressure_long_window', 'trend_dominant', 'tuned']   ← ha_live_actual gone
```

`_extract_model_rows` on `history/2026-08-13.html` returns 10 models where 2026-08-12 returned 11.
The production model vanishing from the homepage with no explanation is worse than showing it with
a "no data" marker, especially when the report itself explains *why*
(`reports/2026-08-13.md:247`: `sensor.rain_probability` has no long-term statistics).

**Fix:** parse `N/A` as `None` and render "no data" explicitly. `MODEL_DESCRIPTIONS`
(`generate_landing_page.py:14-27`) already knows every model name; the "Current Models" list should
be the union of the report's models and the description table, with a per-model status.

#### B5. The published `docs/` pages are stale and contain benchmarks the changelog declares invalid

`deploy-pages.yml:70-79` converts exactly one document — `docs_site/GLOSSARY.md`. But
`origin/gh-pages` also carries four other doc pages that were generated once, by hand, in commit
`085cd6e`, and are never regenerated:

```
docs/MODELS.html         gh-pages: 2026-08-03    master docs_site/MODELS.md:        2026-08-13
docs/DATA_SOURCES.html   gh-pages: 2026-07-30    master docs_site/DATA_SOURCES.md:  2026-08-13
docs/CLI_RUNNER.html     gh-pages: 2026-07-30    master docs_site/CLI_RUNNER.md:    2026-08-13
docs/BASELINE_MODEL.html gh-pages: 2026-07-30    master docs_site/BASELINE_MODEL.md:2026-07-23
```

All three of the first group were rewritten today as part of the fix. `docs/MODELS.html` is live,
crawlable, and serves the pre-fix rankings that `CHANGELOG.md:7-10` says are "statistical noise"
and "superseded". Nothing on the site links to them (the landing page links to GitHub blob URLs
instead — `generate_landing_page.py:218-238`), which makes them worse, not better: unreachable
from the nav, still reachable from Google.

#### B6. `MODEL_DESCRIPTIONS` publishes hardcoded, superseded F1 numbers

`scripts_utils/generate_landing_page.py:15-20`:

```python
"original":       "Baseline v0.1 — dew-point spread + trend (F1=0.440)",
"tuned":          "Grid-search optimized parameters (F1=0.441)",
"trend_dominant": "❌ Failed experiment — trend-primary (F1=0.115, worst)",
"ha_live_actual": "✅ Production — actual HA sensor (F1=0.484)",
```

Those constants are baked into the homepage next to each model. They are pre-2026-08-13 numbers,
which the changelog says are invalid; today's report scores `tuned` at 0.273, not 0.441. The
homepage therefore shows a live 0.273 in "Latest Results" and a stale 0.441 in "Current Models",
three sections apart.

**Fix:** strip the numbers from the descriptions (keep the prose and the ✅/❌ markers, which
`_is_failed_experiment` depends on — `generate_landing_page.py:35-42`) and let the live table
supply the figures.

#### B7. `docs_site/CHANGELOG.md` is never published, but the metrics page tells readers to read it

`generate_metrics_page.py:376-380` renders a banner on every metrics page:

> ⚠️ Points before **2026-08-13** come from the pre-fix harness … They are not comparable with
> later points — **see the changelog.**

There is no changelog page on the site (`git ls-tree -r --name-only origin/gh-pages` — no
`CHANGELOG`), and no link. The one document that explains why half the chart is meaningless is
the one document the pipeline does not publish.

---

### FRAGILE

#### F1. No `concurrency:` group, and the push has no rebase — overlapping runs lose work

`deploy-pages.yml` has no `concurrency:` key (verified: `grep -n 'concurrency' .github/workflows/*.yml`
returns nothing). The trigger fires on `reports/**`, `scripts_utils/**`, `docs_site/**` and the
workflow file itself (lines 7-11), so a single commit touching a report *and* a script starts one
run, and two commits in quick succession start two. Both do `git fetch origin gh-pages;
git checkout gh-pages` (lines 32-35) against the *same* commit, both regenerate everything, and
both `git push origin gh-pages` (line 102) with no `--force`, no pull, no retry. The loser gets a
non-fast-forward rejection, the job fails red, and its output is simply gone.

This is not hypothetical — the gh-pages log shows runs landing one minute apart:

```
2b038c0 Update GitHub Pages: 2026-08-13 15:23 UTC
7206047 Update GitHub Pages: 2026-08-13 15:24 UTC
2be3a10 Update GitHub Pages: 2026-08-13 19:05 UTC
42f4118 Update GitHub Pages: 2026-08-13 19:13 UTC
```

**Fix:** `concurrency: {group: deploy-pages, cancel-in-progress: false}` (do **not** cancel — a
cancelled run leaves the branch fine, but cancelling mid-push is worse than queueing), plus a
`git pull --rebase origin gh-pages` before push as a belt-and-braces retry.

#### F2. Generators exit 0 when their input is missing, so a half-built site publishes

Verified by running each in an empty directory:

```
generate_landing_page.py   ❌ current/index.html not found — skipping landing page   exit=0
generate_metrics_page.py   ❌ history/ not found — skipping                          exit=0
generate_history_index.py  FileNotFoundError: 'history/index.html'                   exit=1
```

Three scripts, three different failure contracts. The two that print `❌` and return `0`
(`generate_landing_page.py:101-104`, `generate_metrics_page.py:118-120` and `182-188`) let
`deploy-pages.yml:85-92` succeed, and the unconditional `git add . && git commit && git push`
(lines 100-102) then publishes whatever *is* on disk. The `❌` is only visible to someone reading
the Actions log.

#### F3. An empty `history/` publishes an empty History page

`generate_history_index.py` does not check that it found anything:

```
$ mkdir -p /tmp/x/history && cd /tmp/x && python generate_history_index.py
✅ Updated history/index.html
exit=0
cards: 0
```

It writes a well-formed page with an empty `<div class="cards">` and reports success. Combined
with `git add .`, a run in which the `git checkout master -- reports/20*.md` step produced
nothing would replace the History index with a blank one. Today the accumulated `history/*.html`
on gh-pages protects against this, but nothing enforces that.

#### F4. The deploy workflow never runs the tests

`deploy-pages.yml` has no `needs:`, no `workflow_run` trigger, and no test step. `tests.yml`
triggers independently on the same `push: master`. The two run in parallel, so a commit that
breaks a generator publishes the broken output at roughly the same moment the test job goes red.
Every finding in the BROKEN section above would have shipped this way.

#### F5. `history/` accumulates and is never pruned or reconciled

The workflow only ever adds. A report renamed or deleted in `master` keeps its HTML on gh-pages
forever, and `generate_history_index.py:91` (`history_dir.glob('*.html')`) keeps carding it.
There is no manifest and no diff against `master`. Related: the loop at `deploy-pages.yml:54-59`
iterates `reports/*.md`, not `reports/20*.md` — it happens to be safe only because the selective
checkout on lines 48-51 is what creates the directory. If `reports/` ever exists in the gh-pages
tree for any reason, `reports/README.md` gets published as `history/README.html`. I reproduced
that by copying the whole `reports/` directory: `history/README.html` was generated.

#### F6. `dates.index(d)` assumes dates are unique

`generate_metrics_page.py:316-317`:

```python
for d in reversed(dates):
    idx = dates.index(d)
```

`dates` is built in filename order, and `index()` returns the *first* occurrence. Two files
yielding the same date (a report re-emitted under a different filename, or a `pressure_variants_*`
report that gains a `# Daily Model Analysis — …` title) would make every row after the duplicate
read from the wrong column. Not reachable with today's file set — I checked all 33 files and every
date is unique — but it is a one-line hazard: iterate indices, not values.

#### F7. `_extract_source_rows` has no table isolation at all

`generate_metrics_page.py:89-112` runs `finditer` over the entire document with no `<table>`
scoping. It survives today only because the pattern requires exactly three cells
(`<td>word</td><td>digits</td><td>anything</td></tr>`) and no other table in the report matches
that shape — I verified all 33 report files return exactly `['OM', 'MS', 'YX']`. But the report
gained two new tables today ("Ground truth source agreement", "Sensor Diagnostics") and will gain
more. A future 3-column table with an integer second column starts contributing phantom
precipitation sources. The `Source` header guard on line 105 is the only defence.

#### F8. No `.nojekyll`

`git ls-tree -r --name-only origin/gh-pages` contains no `.nojekyll`. Nothing on the site starts
with `_` today so Jekyll is passing the files through, but the moment any generated path does,
GitHub Pages will silently drop it. A zero-byte file removes the whole class of problem.

#### F9. Plotly is loaded from a third-party CDN with no SRI and no fallback

`generate_metrics_page.py:347`:

```html
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
```

No `integrity`, no `crossorigin`, no local copy. If `cdn.plot.ly` is unreachable or the file
changes, all five charts render as empty 350-450px boxes (`renderChart` at line 452 only handles
*empty trace arrays*, not a missing `Plotly` global — it would throw `ReferenceError` on the first
`Plotly.newPlot`). The static data table below still renders, which is the saving grace.

---

### QUALITY

#### Q1. `metrics/index.html` is 71 KB, and 76% of it is a JSON blob the page barely uses

Measured: the file is 71,767 bytes; the inline `const cfg = {…}` literal is 54,771 bytes. The same
data is *also* written to `metrics/data.json` (30,015 bytes) at `generate_metrics_page.py:543`.
So the payload ships twice, once inline and once as a file, and the inline copy blocks parsing.
Fetching `data.json` at runtime (or trimming `chart_data` to what the charts actually need) would
cut the HTML to well under 20 KB.

#### Q2. The brand colour fails WCAG AA for normal text everywhere it is used

`assets/style.css` uses `#667eea` for nav links, `h2`, card headings, table headers and footer
links. Contrast ratios computed against the actual backgrounds:

| Usage | Ratio | Verdict |
|---|---|---|
| `nav a` `#667eea` on `#fff` | 3.66:1 | fails AA (needs 4.5:1) |
| `h2` `#667eea` on `#fff` | 3.66:1 | passes as large text only |
| `th` `#667eea` on `#f8f9fa` | 3.47:1 | fails AA |
| `footer a` `#667eea` on `#333` | 3.45:1 | fails AA |
| `.status-warning` `#ffc107` on `#fff` | 1.63:1 | fails badly |
| chart "No data" `#999` on `#fff` | 2.85:1 | fails |
| failed-experiment warning `#ff6b6b` on `.report-card` | 2.59:1 | fails |

The last one is the most consequential: `generate_landing_page.py:141` renders
`⚠️ This is a known failed experiment` in `#ff6b6b` on the light `.report-card` gradient. The one
piece of text on the site whose entire job is to be noticed has the worst contrast on the page.
Darkening the accent to roughly `#4c5fd7` fixes the first four at once.

#### Q3. Tables overflow on mobile — there is no scroll container anywhere

The only `overflow` rule in the entire stylesheet is `pre { overflow-x: auto }` (line 212).
`table { width: 100% }` with `th, td { padding: 0.75rem }` and no wrapper means the widest table in
a daily report — Temporal Metrics, 6 columns × 34 rows, with cells like `pressure_long_window` —
forces horizontal scrolling of the whole page on a phone. The `@media (max-width: 768px)` block
only shrinks the header and section padding.

#### Q4. `md_to_html.py` renders four markdown constructs as literal text

Verified against the generated `current/index.html`:

- **Bullet lists** — no `<ul>`/`<li>` support. `- Home Assistant: 1033 rows, …` renders as
  `<p>- Home Assistant: 1033 rows…<br>`. The entire new "Source data ranges" and "Ground truth
  distribution" blocks are affected.
- **Italics** — no `_…_` or `*…*` handling. The new caveat line renders with its underscores
  visible: `_N/A means no threshold reached the precision floor in that window — not a score of
  zero._` and `_Report generated by daily_analysis.py at …_`.
- **Horizontal rules** — `grep -c '<hr' current/index.html` → 0. The `---` separators are
  swallowed by the paragraph logic.
- **Fenced code blocks** — unhandled (`convert_docs_to_html.py:74-80` handles them; `md_to_html.py`
  does not).

A better converter already exists in this repo: `scripts_utils/convert_glossary_to_html.py`
handles lists (39-42), italics (24), `<hr>` (33) and fenced blocks (36). It is dead code (see M3).

#### Q5. Missing page furniture

Verified across all five generated page types (`index.html`, `current/index.html`,
`history/index.html`, `metrics/index.html`, `docs/GLOSSARY.html`): zero `<noscript>`, zero
`<meta name="description">`, zero favicon links, zero `alt` attributes (no `<img>` either), no
`404.html`, no `robots.txt`, no sitemap, no dark-mode support. Report pages and the glossary emit
**two `<h1>`s** — the site header plus the document title — which breaks the document outline for
screen readers.

#### Q6. The landing page nav is missing the Glossary link

`generate_landing_page.py:159-164` emits four nav links; every other generator emits five
(`md_to_html.py:98-104`, `generate_history_index.py:152-158`,
`generate_metrics_page.py:383-389`, `convert_docs_to_html.py:114-120`). The homepage is the only
page from which the Glossary is not one click away (it is reachable from the Documentation card at
line 213, but not the nav).

Note: the nav links themselves are **not** broken. I resolved every `href` on gh-pages against
`git ls-tree -r --name-only origin/gh-pages` — `../current/index.html`, `../history/index.html`,
`../metrics/index.html`, `../docs/GLOSSARY.html` and all 33 history card links all exist.

#### Q7. Six emitted CSS classes have no styles; three defined classes are never emitted

Emitted by generators but absent from `assets/style.css`: `report-content`, `docs-content`,
`intro`, `latest`, `quick-links`, `documentation`. Defined in the stylesheet but never emitted:
`status-good`, `status-warning`, `status-bad`. (`chart-container` / `chart-row` are styled inline
in `generate_metrics_page.py:348-370`, which is why they work.)

---

### MAINTAINABILITY

#### M1. The same three parsers are copy-pasted across three files

- `_strip_tags` — `generate_landing_page.py:30` and `generate_metrics_page.py:49`, plus an
  inline `re.sub(r'<[^>]+>', '', …)` at `generate_history_index.py:22`.
- `re.search(r'Best overall[^:]*:\s*([\w_]+)', text)` — three identical copies:
  `generate_landing_page.py:57`, `generate_history_index.py:31`, `generate_metrics_page.py:85`.
- `re.search(r'Daily Model Analysis[^—]*[—–-]\s*(\d{4}-\d{2}-\d{2})', text)` — two copies:
  `generate_landing_page.py:52`, `generate_metrics_page.py:54`.
- Leaderboard-F1 extraction — three *divergent* implementations, one correct
  (`generate_history_index.py:57-61`, `<td>`-anchored) and one wrong (`generate_landing_page.py:62`,
  unanchored). That divergence is finding B3.

This is the root cause of B1/B2/B3 being three separate bugs instead of one. A single
`scripts_utils/report_parse.py` with `strip_tags`, `extract_date`, `extract_best_model`,
`extract_leaderboard(html) -> list[ModelRow]` and an explicit `N/A → None` convention would
collapse them.

#### M2. HTML chrome is duplicated across six generators

Every one of `md_to_html.py`, `generate_history_index.py`, `generate_landing_page.py`,
`generate_metrics_page.py`, `convert_docs_to_html.py`, `convert_glossary_to_html.py` contains its
own `<!DOCTYPE html>` … `<head>` … `<header>` … `<nav>` … `<footer>` block. Q6 (missing Glossary
link) and Q5 (no favicon/meta anywhere) are direct consequences: there is no single place to add
one. A shared `page_shell(title, nav_active, body)` helper would fix both classes of problem at
once and is a strictly mechanical refactor.

#### M3. Dead code and dead assertions

- `scripts_utils/convert_glossary_to_html.py` reads `docs/GLOSSARY.md` (line 129), which does not
  exist in `master` — `docs/` contains only `architecture.md`, `AUTHENTICATION.md`,
  `DEVELOPMENT.md`. The glossary lives at `docs_site/GLOSSARY.md`. The script is never invoked by
  any workflow. It is also the *best* markdown converter in the repo (see Q4) — salvage its
  converter, delete the rest.
- `tests/test_md_to_html.py:9`, `tests/test_generate_history_index.py:9` and
  `tests/test_generate_metrics_page.py:6` all `sys.path.insert(0, …/"scripts")`. There is no
  `scripts/` directory; the imports work only because `tests/conftest.py:17-22` adds
  `scripts_utils/`. Three misleading no-ops.
- `tests/test_workflow_yaml.py:79-95` asserts on `python3 scripts/generate_history_index\.py`
  (old path) and is guarded by `not has_heredoc or …`, so it passes vacuously — it can never fail.
- `tests/test_generate_history_index.py:25-48` is named `…_multiple_tables` and claims to prove
  first-table isolation, but only tests models present in the first table. It is precisely the
  test that should have caught B2 and does not.

#### M4. Build artifacts are committed to `master`, and they are stale garbage

- `history/index.html` (1,311 bytes) contains exactly one card, for `report_2026-07-01`, linking
  to `report_2026-07-01.html` — a file that exists nowhere in the repo or on gh-pages.
- `metrics/index.html` (71,767 bytes) and `metrics/data.json` (30,015 bytes) differ from the
  gh-pages copies and were regenerated into `master` by commit `3a7eea8`.
- `docs_site/GLOSSARY.html` (12,996 bytes) is a build output committed next to its source.

These exist because the generators write to `Path("history")`, `Path("metrics")` and
`Path("index.html")` relative to the *current working directory*
(`generate_history_index.py:90,177`; `generate_metrics_page.py:118,537,540,543`;
`generate_landing_page.py:101,251`). Running any of them from the repo root — which is the natural
thing to do while developing — silently writes into `master`'s tree. Add `--output-dir` (default
`.`) and `.gitignore` the outputs.

#### M5. CI hygiene

| Item | Evidence | Impact |
|---|---|---|
| `actions/checkout@v3` | `deploy-pages.yml:22`, `tests.yml:14` | Node 16 runtime, deprecated |
| `actions/setup-python@v4` | `deploy-pages.yml:28`, `tests.yml:17` | same |
| Python version mismatch | `tests.yml:19` → `3.10`; `deploy-pages.yml:30` → `3.11` | tests never run on the deploy interpreter |
| No pip cache | `tests.yml:21-24` | `requirements.txt` pulls `jupyter`, `pandas`, `matplotlib` on every run for a suite that finishes in 8 s |
| `pytest-cov` installed ad hoc | `tests.yml:31-32` | not in `requirements.txt`; suite runs twice (lines 28 and 33) |
| `fetch-depth: 0` | `deploy-pages.yml:25` | full history + ~190 remote branches, for a job that needs `master` and `gh-pages` only |
| `permissions: contents: write` | `deploy-pages.yml:14-15` | job-wide write for a step that only needs to push one branch |
| No `workflow_dispatch` inputs | `deploy-pages.yml:12` | no dry-run, no "rebuild everything" switch |
| No failure notification | — | a red deploy is invisible unless someone opens Actions |
| Over-broad trigger | `deploy-pages.yml:9` | any change to `scripts_utils/**` (e.g. `fetch_meteostat.py`) redeploys the whole site |
| `datetime.utcnow()` | `md_to_html.py:114`, `convert_docs_to_html.py:130`, `generate_landing_page.py:109`, `generate_metrics_page.py:337` | deprecated in 3.12+; blocks the Python upgrade |

Two smaller ones, unverified in CI but worth noting: `read_text()`/`write_text()` are called
without `encoding=` in every generator (`md_to_html.py:134,140` etc.), so they depend on the
runner locale — this is almost certainly fine on `ubuntu-latest` thanks to PEP 538 C-locale
coercion, but the files are full of em-dashes, `κ` and emoji, so pinning `encoding="utf-8"` costs
nothing. And `gh-pages` carries its own stale copy of `.github/workflows/deploy-pages.yml`
(it differs from `master`'s — `git diff origin/gh-pages:… master:…`), which is confusing but
harmless since the workflow only triggers on `master`.

---

## Plan

### Stage 1 — Stop publishing wrong numbers _(fixes B1, B2, B3, B4)_

1. **New module `scripts_utils/report_parse.py`.** Move `strip_tags`, `extract_date`,
   `extract_best_model` there (lifted verbatim from `generate_metrics_page.py:49-55,84-86`), and
   add one authoritative leaderboard parser:

   - Locate the leaderboard by heading, not position: find `<h2>Model Performance` and take the
     first `<table>` after it. Fall back to the first table in the document *only* if that heading
     is absent (pre-2026-07-21 reports), and record which path was used.
   - Cell pattern becomes `(N/A|[0-9.]+(?:[eE][+-]?\d+)?)`, mapped to `None` for `N/A`.
   - Row pattern keeps the `<tr>\s*<td>…` anchor from `generate_history_index.py:57-61` — this is
     the correct one; do not reuse `generate_landing_page.py:62`.
   - Return `list[dict]` with `model`, `f1`, `precision`, `recall`, each possibly `None`, and
     never search outside the located table.

2. **`generate_metrics_page.py`** — replace `_extract_model_rows` (58-81) with a call to the shared
   parser. Keep `None` values flowing into `model_series`; the plotting code at lines 215-238 and
   244-259 already skips `None` correctly. Add "leaderboard contained no numeric rows" to the
   `skipped_files` list (135, 190-194) so it is reported rather than silently substituted.

3. **`generate_history_index.py`** — delete `_extract_f1_from_leaderboard` (44-66), call the shared
   parser, and render `no data` when the best model's F1 is `None` instead of falling through.

4. **`generate_landing_page.py`** — delete the inline `f1_m` regex (61-65) and `_detect_models`
   (75-97); both become calls to the shared parser. Render models with `None` metrics as
   `⚪ no data` in the "Current Models" list rather than omitting them.

5. **Tests.** Add `tests/test_report_parse.py` covering: an all-`N/A` leaderboard returns rows with
   `None` (never temporal-metrics numbers); a model that is `N/A` in the leaderboard but numeric in
   Temporal Metrics returns `None`; `combined` does not match `pressure_combined`; the real
   `reports/2026-08-13.md` yields 11 models with `ha_live_actual` present and `f1 is None`. Fix
   `tests/test_generate_history_index.py:25-48` so it actually asserts isolation.

### Stage 2 — Make failure visible _(fixes F1, F2, F3, F4)_

6. **`deploy-pages.yml`** — add at the top:

   ```yaml
   concurrency:
     group: deploy-pages
     cancel-in-progress: false
   ```

7. **Run the tests before publishing.** Either add a `test` job and `needs: test` to `deploy`, or
   convert `deploy-pages.yml` to a `workflow_run` trigger on `Tests` completing successfully. The
   former is simpler and keeps the existing trigger semantics.

8. **Make the generators fail loudly.** Replace the `print("❌ …"); return` paths in
   `generate_landing_page.py:101-104` and `generate_metrics_page.py:118-120,182-188` with
   `sys.exit(1)`. Add a guard in `generate_history_index.py` that exits non-zero when zero cards
   were produced. Add `set -euo pipefail` at the top of each multi-line `run:` block.

9. **Rebase before push.** In `deploy-pages.yml:94-102`, insert `git pull --rebase origin gh-pages`
   before `git push`, so a lost concurrency race self-heals instead of failing.

10. **Sanity gate before commit.** New step after the generators: assert that `index.html`,
    `current/index.html`, `history/index.html`, `metrics/index.html` and `metrics/data.json` all
    exist and are non-trivial (say >1 KB), that `history/index.html` contains at least as many
    cards as the previous commit, and that `metrics/data.json` parses and its `dates` array has not
    shrunk. Abort the deploy otherwise. This is the single highest-value addition in the plan: it
    turns every "silently publishes garbage" finding into a red build.

### Stage 3 — Publish the documents that matter _(fixes B5, B6, B7)_

11. **Convert all of `docs_site/*.md`**, not just `GLOSSARY.md`. Change `deploy-pages.yml:70-79`
    to `git checkout master -- docs_site/` and loop, so `MODELS.md`, `DATA_SOURCES.md`,
    `CLI_RUNNER.md`, `BASELINE_MODEL.md`, `HA_DATA_FETCHER.md`,
    `daily_analysis_output_format.md` and **`CHANGELOG.md`** all get pages. This automatically
    un-stales the four orphaned pages in B5.

12. **Link the changelog.** Add it to the nav (or at minimum turn the "see the changelog" text at
    `generate_metrics_page.py:379` into an actual `<a href="../docs/CHANGELOG.html">`) and add a
    Documentation card for it in `generate_landing_page.py:207-241`. While there, change the
    MODELS/BASELINE/DATA_SOURCES/CLI_RUNNER cards from GitHub blob URLs to the local
    `docs/*.html` pages now that they are fresh.

13. **Strip the hardcoded F1 values** from `MODEL_DESCRIPTIONS`
    (`generate_landing_page.py:15-20`). Keep the ✅/❌ prefixes — `_is_failed_experiment` and
    `tests/test_landing_page_failed_models.py:32-46` depend on them.

### Stage 4 — Shared page shell and converter _(fixes Q4, Q5, Q6, Q7, M2, M3)_

14. **`scripts_utils/page_shell.py`** with one `render_page(title, description, nav_active, body,
    depth)` function. Migrate all six generators onto it. Add in that one place: `<meta
    name="description">`, a favicon, a single `<h1>` per page (demote the report title to `<h2>` or
    drop the site header `<h1>` on inner pages), a skip-to-content link, and the missing Glossary
    nav entry.

15. **Consolidate the markdown converters.** Take the list / italic / `<hr>` / fenced-code handling
    from `convert_glossary_to_html.py:24-42` into `md_to_html.py`, then delete
    `convert_glossary_to_html.py` and fold `convert_docs_to_html.py` into `md_to_html.py` behind a
    `--style docs|report` flag. One converter, one table parser, one set of tests.

16. **Stylesheet.** `assets/style.css` lives only on gh-pages — move it into `master` (say
    `site/assets/style.css`) and have the workflow copy it, so it is reviewable. Then: darken
    `#667eea` to ~`#4c5fd7`; wrap tables in `.table-wrap { overflow-x: auto }` and have the
    converters emit the wrapper; darken `#ff6b6b` and `#999`; delete `.status-*`; add styles for
    the six orphaned classes or stop emitting them; add a `prefers-color-scheme: dark` block.

17. **Add `.nojekyll`, `404.html`, and a favicon** to the gh-pages payload.

### Stage 5 — Hygiene and capability _(fixes Q1, F5, F9, M4, M5)_

18. **Actions and Python.** Bump `actions/checkout` and `actions/setup-python` to current majors in
    both workflows; pin both to the same Python (3.11, or 3.12 after replacing `datetime.utcnow()`
    with `datetime.now(timezone.utc)` in the four call sites); add
    `cache: pip` to `setup-python` in `tests.yml`; move `pytest-cov` into `requirements.txt` and
    run the suite once with `--cov` instead of twice; replace `fetch-depth: 0` with a shallow
    fetch of just `master` and `gh-pages`.

19. **Trim `metrics/index.html`.** Stop inlining `chart_data`; the page already writes
    `metrics/data.json`. Either `fetch()` it on load or inline only the pre-built traces
    (`chart_config`), dropping the redundant `chart_data` copy. Add `integrity` + `crossorigin` to
    the Plotly `<script>`, or vendor it into `assets/`.

20. **Un-commit the build artifacts.** Delete `history/index.html`, `metrics/index.html`,
    `metrics/data.json` and `docs_site/GLOSSARY.html` from `master`; add them to `.gitignore`; give
    each generator an `--output-dir` argument (default `.`) so running one locally cannot pollute
    the repo root again.

21. **Prune `history/`.** Have the workflow write a manifest of the reports it converted this run
    and delete any `history/*.html` not in it, so gh-pages tracks `master` instead of only growing.
    Tighten `deploy-pages.yml:54` from `reports/*.md` to `reports/20*.md` +
    `reports/pressure_variants_*.md`.

22. **Dead code and dead tests.** Remove the three `sys.path.insert(…, "scripts")` no-ops
    (`test_md_to_html.py:9`, `test_generate_history_index.py:9`, `test_generate_metrics_page.py:6`)
    and the vacuous `test_deploy_pages_uses_script_not_inline`
    (`test_workflow_yaml.py:79-95`); replace the latter with assertions that actually matter —
    that `deploy-pages.yml` declares a `concurrency` group, that it runs tests before publishing,
    and that every script it invokes exists in `scripts_utils/`.

23. **Nice-to-haves, in rough value order:** a `workflow_dispatch` `dry_run` input that runs
    everything and uploads the result as an artifact instead of pushing; a link-checker step over
    the generated tree; an RSS/Atom feed built from `history/` (the data is already in
    `metrics/data.json`); a `failure()`-conditioned step that opens or comments on an issue.

---

## Verification

Set up a scratch mirror of the deploy once, and re-run it after each stage. This is exactly what
the workflow does, minus the git plumbing:

```bash
R=/home/kanstancin/Documents/projects/rain-analysis
W=/tmp/ghpages-check && rm -rf $W && mkdir -p $W/{history,current,docs,metrics,docs_site}
cd $W
cp -r $R/scripts_utils .
cp $R/reports/20*.md $R/reports/pressure_variants_*.md reports_tmp/ 2>/dev/null || \
  { mkdir -p reports; cp $R/reports/20*.md $R/reports/pressure_variants_*.md reports/; }
cp $R/docs_site/*.md docs_site/
for r in reports/*.md; do $R/.venv/bin/python scripts_utils/md_to_html.py "$r" "history/$(basename "$r" .md).html"; done
$R/.venv/bin/python scripts_utils/md_to_html.py "$(ls -1 reports/20*.md | sort | tail -1)" current/index.html
$R/.venv/bin/python scripts_utils/convert_docs_to_html.py docs_site/GLOSSARY.md docs/GLOSSARY.html
$R/.venv/bin/python scripts_utils/generate_history_index.py
$R/.venv/bin/python scripts_utils/generate_landing_page.py
$R/.venv/bin/python scripts_utils/generate_metrics_page.py
```

**Stage 1 — the numbers are right.**

```bash
# ha_live_actual must be present with a null metric, not absent (B4)
cd $W && python -c "
import json; d=json.load(open('metrics/data.json')); i=d['dates'].index('2026-08-13')
assert 'ha_live_actual' in d['models'], 'production model dropped'
assert d['models']['ha_live_actual']['f1'][i] is None, 'N/A parsed as a number'
print('OK: ha_live_actual present, f1 is null')"

# the landing page must list it
grep -c 'ha_live_actual' $W/index.html   # expect >= 1

# the fall-through must be gone (B1): blank the leaderboard and confirm the day is SKIPPED
cp $W/history/2026-08-13.html /tmp/na.html
python - <<'PY'
import re
h=open('/tmp/na.html').read(); head,sep,tail=h.partition('</table>')
open('/tmp/na.html','w').write(re.sub(r'<td>[0-9]+\.[0-9]+</td>','<td>N/A</td>',head)+sep+tail)
PY
# after the fix, extract_leaderboard('/tmp/na.html') must return rows whose metrics are all None
# — never 0.444/0.452/0.553, which are the Temporal Metrics values.

.venv/bin/python -m pytest tests/test_report_parse.py tests/test_generate_history_index.py \
  tests/test_generate_metrics_page.py tests/test_landing_page_failed_models.py -q
```

**Stage 2 — failure is loud.**

```bash
# every generator must now exit non-zero on missing input
T=/tmp/empty && rm -rf $T && mkdir $T && cd $T
for s in generate_landing_page generate_metrics_page generate_history_index; do
  $R/.venv/bin/python $R/scripts_utils/$s.py; echo "$s exit=$?"   # all must be non-zero
done
# empty-but-present history/ must also fail
mkdir -p $T/history && cd $T && $R/.venv/bin/python $R/scripts_utils/generate_history_index.py; echo "exit=$?"

# workflow shape
grep -q 'concurrency:' $R/.github/workflows/deploy-pages.yml && echo "concurrency OK"
grep -q 'needs:\|workflow_run' $R/.github/workflows/deploy-pages.yml && echo "gated on tests OK"
.venv/bin/python -m pytest tests/test_workflow_yaml.py -q
```

Then push a deliberately-broken generator to a scratch branch and confirm the deploy job goes red
*before* the commit step rather than after.

**Stage 3 — the documents are there.** After a real deploy:

```bash
git fetch origin gh-pages
git ls-tree -r --name-only origin/gh-pages | grep '^docs/'   # expect CHANGELOG.html + all of docs_site
for f in MODELS DATA_SOURCES CLI_RUNNER CHANGELOG; do
  echo "$f: $(git log -1 --format=%ci origin/gh-pages -- docs/$f.html)"   # all must be today
done
git show origin/gh-pages:metrics/index.html | grep -o 'href="[^"]*CHANGELOG[^"]*"'   # link exists
git show origin/gh-pages:index.html | grep -c 'F1=0.4'   # expect 0 (B6)
```

**Stage 4 — output quality.**

```bash
# one h1 per page
for f in $W/index.html $W/current/index.html $W/metrics/index.html $W/docs/GLOSSARY.html; do
  echo "$f: $(grep -c '<h1' $f)"   # all must be 1
done
# furniture present
grep -l 'name="description"' $W/index.html $W/current/index.html $W/metrics/index.html
grep -l 'rel="icon"' $W/index.html
# nav consistent across every generated page
grep -o 'GLOSSARY.html' $W/index.html   # must now match
# markdown fully converted — these must all be 0
grep -c '^<p>- ' $W/current/index.html
grep -o '_[A-Z][^_]\{5,60\}_' $W/current/index.html | wc -l
grep -c '<ul>' $W/current/index.html    # must be > 0
grep -c '<hr' $W/current/index.html     # must be > 0
```

Contrast: re-run the ratio calculation used in Q2 against the new palette and require ≥4.5:1 for
`nav a`, `th`, `footer a` and the failed-experiment warning. Responsiveness: open
`current/index.html` at a 375 px viewport and confirm `document.documentElement.scrollWidth ===
window.innerWidth` (no page-level horizontal scroll).

**Stage 5 — weight, hygiene, artifacts.**

```bash
wc -c $W/metrics/index.html          # target < 20000 (was 71767)
grep -c 'integrity=' $W/metrics/index.html   # expect 1 if using CDN + SRI
git ls-tree -r --name-only origin/gh-pages | grep -c nojekyll   # expect 1
git -C $R status --short             # clean after running the generators from the repo root
git -C $R ls-files | grep -E '^(history/index.html|metrics/(index.html|data.json)|docs_site/GLOSSARY.html)$'
                                     # expect no output — artifacts removed from master
grep -n 'checkout@\|setup-python@\|python-version' $R/.github/workflows/*.yml
                                     # same major versions, same Python in both files
grep -c 'utcnow' $R/scripts_utils/*.py   # expect 0
```

Finally, after the first post-fix deploy, diff the published metrics data against the pre-fix copy
and confirm nothing moved except the intended `ha_live_actual` nulls:

```bash
git show origin/gh-pages~1:metrics/data.json > /tmp/before.json
git show origin/gh-pages:metrics/data.json  > /tmp/after.json
python -c "
import json
a=json.load(open('/tmp/before.json')); b=json.load(open('/tmp/after.json'))
for m in sorted(set(a['models'])|set(b['models'])):
    for k in ('f1','precision','recall'):
        x=a['models'].get(m,{}).get(k,[]); y=b['models'].get(m,{}).get(k,[])
        d=[(i,p,q) for i,(p,q) in enumerate(zip(x,y)) if p!=q]
        if d: print(m,k,d[:5])"
```
