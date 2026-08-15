# Plans

Audits and improvement plans. Each document states its evidence so the claims can be
re-checked rather than taken on trust; neither has been acted on yet.

| Document | Subject | Headline |
|---|---|---|
| [model-improvements.md](model-improvements.md) | The prediction models themselves | The deployed alert catches under 12% of rain events, and the dew-point-spread derivative every model is built on scores AUC 0.49 |
| [gh-pages-improvements.md](gh-pages-improvements.md) | The GitHub Pages publishing pipeline | Report parsers fall through to the wrong table when a metric is `N/A`, and can publish temporal-tolerance scores as plain F1 |
| [backfill-conclusions.md](backfill-conclusions.md) | The recomputed 2026-07-13 → 2026-08-13 record | Persistence beats every hand-written model; only the learned model beats persistence; 7-day windows cannot rank anything |

Both were written on 2026-08-13, immediately after the analysis-harness fixes recorded
in [`docs_site/CHANGELOG.md`](../docs_site/CHANGELOG.md). That work is their shared
starting point in two ways:

- It made model scores trustworthy for the first time, which is what allowed the model
  audit to conclude anything at all — the previous ~17 labelled rain hours could not
  have separated a good model from a bad one.
- It changed the daily report format, and the publishing pipeline parses that format
  with regexes. Several findings in the gh-pages audit are consequences of that change
  rather than long-standing bugs; they are marked as such.
