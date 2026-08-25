# Backend Architecture

Last rewritten: 2026-08-25, against the code as it actually is. Earlier
revisions of this document described planned directories (`ml/`, `scripts/`)
and endpoint layouts that never existed; when this document and the code
disagree, the code wins and this file gets fixed.

## System overview

```
Home Assistant ──POST /api/v1/data/measurements──► ┌───────────────┐
  (automation on state change, write-scoped key)   │               │
                                                   │    Backend    │
Analysis pipeline ──POST /api/v1/reports─────────► │   (FastAPI)   │
  (daily_analysis.py, variant B: the pipeline      │               │
   is the only calculator; also pushes             │    SQLite     │
   openmeteo.precipitation as ground truth)        └───────┬───────┘
                                                           │
Browser (GitHub Pages widget) ──GET /api/v1/data/current──┘
  (public read-only key baked into the page, #407)
```

Two design rules carry most of the weight:

- **The backend never reaches out.** No outbound HTTP: Home Assistant and
  the pipeline push data in; the backend stores and serves. Gaps are
  repaired by re-running the (idempotent) push scripts.
- **Push endpoints are idempotent upserts.** Measurements upsert on
  (sensor, timestamp), predictions on (model, timestamp), reports and
  metrics by date — re-delivery after restarts or reruns never duplicates.

## Repository layout (actual)

```
backend/
├── app/
│   ├── auth/           # API-key crypto, middleware, scope dependencies
│   ├── ml/             # model loading/serving, daily task, metrics
│   ├── models/         # SQLAlchemy ORM (one file per table group)
│   ├── routers/        # admin, auth, data, models, predictions, reports
│   ├── schemas/        # Pydantic (canonical ML schemas in schemas/ml.py)
│   ├── services/       # measurement_service, report_service
│   ├── config.py       # pydantic-settings (.env)
│   ├── constants.py    # EXEMPT_PATHS — single auth-exemption list
│   ├── database.py     # async engine/session; alembic owns the schema
│   └── main.py         # app wiring: middleware, /api/v1 router, health
├── alembic/            # migrations (the only thing that creates tables)
├── models/             # model pickles (gitignored), settings.models_dir
├── scripts/            # create_admin_key.py, register_model.py
└── tests/              # backend suite (runs from backend/, see pytest.ini)
```

Related repo-level pieces: `analysis/` (rainlib and the analysis pipeline),
`rainlib/` (shim package the backend imports for formula models),
`scripts_utils/` (pipeline + site generators + push/migration scripts),
`site/` (static site assets incl. the live widget), `docs_site/` (published
docs).

## URL space

Everything lives under `/api/v1/` (decision 2026-08-25, closing the
`/api/v1`-vs-bare ambiguity from #232/#407). Unversioned and key-exempt:
`/`, `/health`, `/health/live`, `/health/ready`, `/docs`, `/openapi.json`,
`/redoc` — the list is `app/constants.py:EXEMPT_PATHS`, shared by the auth
middleware and the OpenAPI customizer.

| Area | Endpoints |
|---|---|
| Data | `POST /api/v1/data/measurements` (write), `GET /api/v1/data/sensors`, `PATCH /api/v1/data/sensors/{id}` (admin), `GET /api/v1/data/measurements`, `GET /api/v1/data/current` |
| Models | `GET /api/v1/models[/{id}[/metrics[/history]]]` |
| Predictions | `GET /api/v1/predictions/current`, `GET /api/v1/predictions/history`, `POST /api/v1/predictions/evaluate` (write) |
| Reports | `POST /api/v1/reports` (write), `GET /api/v1/reports[/{date}|/latest]` |
| Auth/admin | `GET /api/v1/auth/check`, `/api/v1/admin/keys*`, `POST /api/v1/admin/ml/trigger-daily-task` |

## Database schema

EAV for sensor data (ratified in #221 — a new sensor is a row, not a
schema change):

- `sensors(id, name UQ, unit, sensor_type numeric|boolean|text, description, created_at)`
- `measurements(id, sensor_id FK, timestamp, value TEXT, source)` —
  UNIQUE (sensor_id, timestamp); values stored as text (#417), decoded
  server-side per `sensor_type` so clients never parse raw text (#412).
  Timestamps normalized to UTC on ingest.
- `models(id, name UQ, version, description, config JSON, active)` —
  `config` is the serving contract: `kind` ("sklearn" | "rainlib"),
  `file_path` or `rainlib_model`, `features` (ordered), `sensor_map`
  ({feature → sensor name}), `threshold`
- `predictions(id, model_id FK, timestamp, probability, threshold, binary_prediction)` — UQ (model_id, timestamp)
- `model_metrics(id, model_id FK, date, brier/f1/f2/precision/recall/calibration_slope, threshold, confusion_matrix JSON)` — UQ (model_id, date)
- `reports(id, report_date UQ, content JSON, meta JSON, created_at, updated_at)` —
  column named `meta`, not the SQLAlchemy-reserved `metadata` (#232);
  `meta.source_markdown` keeps migrated reports reversible
- `api_keys`, `api_requests_log`, `admin_audit_log` — see
  [AUTHENTICATION.md](AUTHENTICATION.md)

Alembic owns the schema; `init_db()` only verifies connectivity. New ORM
models must be exported from `app/models/__init__.py` or autogenerate will
not see them.

## Authentication

API keys only, `X-API-Key` header, no JWT (#225). Scopes `read < write <
admin` checked by a single hierarchy dependency
(`app/auth/dependencies.py:require_api_key`). The middleware authenticates
every non-exempt path, enforces `expires_at`, per-key rate limits
(in-memory — hence exactly one worker until #421), and writes the request
log + `last_used_at` in one commit.

## ML serving

`PredictionService` resolves an estimator per `models.config.kind`:

- **sklearn**: pickle via `ModelCache` from `config.file_path` (relative to
  `settings.models_dir`) or `{models_dir}/{name}.pkl`. Persisted fitted
  models carry their feature list in `config.features`.
- **rainlib**: `app/ml/rainlib_models.py` adapts the shared formula models
  from `analysis/rainlib.py` (via the `rainlib` shim) to the
  `predict_proba` interface — the analysis and serving sides literally run
  the same code.

`predict()` is sync CPU work and is always called through
`asyncio.to_thread`. `backend/scripts/register_model.py` registers models.

The daily task (APScheduler `AsyncIOScheduler`, 00:00 UTC, manual trigger
via admin endpoint) reads yesterday's measurements for the union of active
models' `sensor_map` sensors, pivots to an hourly frame (forward-fill up
to 2h), predicts and upserts per model, then computes metrics against
`openmeteo.precipitation` ground truth (skipping days with fewer than 6
matched hours).

## Reports

Variant B (#402): `scripts_utils/daily_analysis.py` remains the only
report calculator and POSTs the finished report when
`RAIN_BACKEND_URL`/`RAIN_BACKEND_KEY` are set; a push failure never fails
the pipeline. History migration:
`scripts_utils/migrate_reports_to_backend.py`, built on the markdown
extractors in `scripts_utils/report_parse.py` — the single parser module
(rule from #232). The corpus test `tests/test_report_parse_corpus.py`
runs the parser over every committed report.

## Configuration

`.env` (see `.env.example`): `DATABASE_URL`, `API_KEYS_SALT` (≥32 chars,
placeholder rejected at startup), `CORS_ORIGINS` (defaults include the
GitHub Pages origin for the live widget), `MODELS_DIR`, `LOG_LEVEL`.

## Testing

Two independent suites: root `pytest tests/` (pipeline/site) and
`cd backend && pytest tests/` (backend; `backend/pytest.ini` sets
`asyncio_mode=auto`). They must not be mixed from the root (#441 — root
`pytest.ini` scopes the bare invocation). CI runs both jobs
(`.github/workflows/tests.yml`). Backend tests reset process-global state
(rate limiter, model cache) between tests via an autouse fixture.

## Known limits / deferred

- In-memory rate limiter → single worker (Phase 6, #421)
- Deployment (docker-compose, build-on-server) — Phase 6 (#415–#423)
- Frontend dashboard — Phase 5 (#406–#414); the static-site widget is the
  interim consumer of `/api/v1/data/current`
- gh-pages migration — Phase 7 (#424–#429)
- `POST /predictions/evaluate` requires write scope, which blocks public
  threshold tooling (#410) — unresolved by design until Phase 5
