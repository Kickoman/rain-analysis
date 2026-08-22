# Rain Analysis

Rain forecasting based on sensor data.

## Project Structure

```
rain-analysis/
├── backend/             # FastAPI web application
│   ├── app/             # Application code
│   │   ├── auth/        # Authentication system
│   │   ├── ml/          # ML model integration
│   │   ├── models/      # SQLAlchemy ORM models
│   │   ├── routers/     # API endpoints
│   │   ├── schemas/     # Pydantic validation schemas
│   │   ├── database.py  # Database setup
│   │   ├── config.py    # Configuration
│   │   └── main.py      # FastAPI application
│   ├── alembic/         # Database migrations
│   ├── scripts/         # Utility scripts (key generation, etc.)
│   └── tests/           # Backend tests
├── analysis/            # ML analysis and model training
│   ├── rainlib.py       # Core ML library (models, training, evaluation)
│   └── rain_analysis.ipynb  # Jupyter notebook for exploration
├── rainlib/             # Shared re-export package for analysis.rainlib
├── scripts_utils/       # Shared data processing utilities
├── data/                # Training data and archives
├── reports/             # Generated analysis reports
├── docs/                # Documentation
└── tests/               # Integration tests
```

## Quick Start

### Backend

```bash
cd backend

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and set:
#   - API_KEYS_SALT (required for authentication)
#   - DATABASE_URL (optional, defaults to SQLite)

# Run database migrations
alembic upgrade head

# Create an admin API key
python scripts/create_admin_key.py

# Start development server
python run.py
```

API documentation: http://localhost:8000/docs

### ML Analysis

```bash
# Install dependencies
pip install -r requirements.txt

# Run full analysis pipeline
python analysis/run_full_analysis.py --days 7 --output-dir reports/
```

See `analysis/` directory for ML model training and evaluation code.

## Authentication

The API uses API keys for authentication. Include your key in the `X-API-Key` header:

```bash
curl -H "X-API-Key: ra_live_..." https://api.example.com/health
```

### Getting Started with Authentication

1. **Create Admin Key**: Use `backend/scripts/create_admin_key.py` to generate your first admin key
2. **Create Additional Keys**: Use admin endpoints to create keys with different scopes and rate limits
3. **Use Your Key**: Include it in the `X-API-Key` header for all API requests

### API Key Scopes

- `read`: Read-only access to data endpoints
- `write`: Data ingestion and modification endpoints
- `admin`: Full access including key management

### Rate Limits

Rate limits are per-key and configurable by admins:

- **RPM**: Requests per minute
- **RPH**: Requests per hour  
- **RPD**: Requests per day

Check your current usage and remaining quota:

```bash
curl -H "X-API-Key: your_key" https://api.example.com/auth/check
```

**Response:**
```json
{
  "valid": true,
  "key_name": "my-app-key",
  "scopes": ["read"],
  "rate_limits": {
    "rpm": {"limit": 60, "remaining": 58, "reset_at": "2026-07-26T18:31:00Z"},
    "rph": {"limit": 1000, "remaining": 995, "reset_at": "2026-07-26T19:00:00Z"},
    "rpd": {"limit": 10000, "remaining": 9987, "reset_at": "2026-07-27T00:00:00Z"}
  }
}
```

For detailed authentication documentation, see [docs/AUTHENTICATION.md](docs/AUTHENTICATION.md).

## Development

### Running Tests

```bash
# Backend tests
cd backend
pytest -v

# With coverage report
pytest -v --cov=app --cov-report=term-missing

# Integration tests
pytest tests/ -v
```

### Database Migrations

```bash
cd backend

# Create new migration
alembic revision --autogenerate -m "Description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

## API Overview

### Core Endpoints

- `GET /health` - Health check
- `GET /` - API information
- `GET /docs` - Interactive API documentation

### Authentication Endpoints

- `GET /auth/check` - Check API key validity and rate limits
- `POST /admin/keys` - Create new API key (admin only)
- `GET /admin/keys` - List API keys (admin only)
- `PATCH /admin/keys/{key_id}` - Update API key (admin only)
- `DELETE /admin/keys/{key_id}` - Revoke API key (admin only)

### Database Schema

The backend uses a flexible schema designed for multiple sensors and ML models:

**Core Data:**
- **sensors** - Sensor definitions (name, type, unit)
- **measurements** - Time-series sensor data
- **models** - ML model metadata
- **predictions** - Model predictions over time
- **model_metrics** - Model performance metrics

**Authentication:**
- **api_keys** - API key definitions with scopes and rate limits
- **api_request_logs** - Request tracking for rate limiting
- **admin_audit_logs** - Audit log for administrative actions

See [docs/architecture.md](docs/architecture.md) for detailed architecture documentation.

## Tech Stack

### Backend
- **FastAPI** - Modern Python web framework
- **SQLAlchemy 2.0** - Async ORM
- **Alembic** - Database migrations
- **Pydantic** - Data validation
- **SQLite/aiosqlite** - Database (development)
- **hashlib (SHA-256) + secrets** - API key generation and hashing

### ML Stack
- **pandas** - Data manipulation
- **numpy** - Numerical computing
- **matplotlib** - Visualization

### Testing
- **pytest** - Test framework
- **pytest-asyncio** - Async test support
- **pytest-cov** - Coverage reporting
- **httpx** - HTTP client for testing

## Documentation

- [Architecture](docs/architecture.md) - System architecture overview
- [Authentication](docs/AUTHENTICATION.md) - API authentication guide
- [Development](docs/DEVELOPMENT.md) - Development guidelines
- [API Documentation](http://localhost:8000/docs) - Interactive API docs (when running)
- [Contributing](CONTRIBUTING.md) - Contribution guidelines

## Roadmap

### Phase 1: Backend Foundation ✅ (Completed)

Phase 1 focused on establishing the backend infrastructure:

1. ✅ Project restructuring
2. ✅ FastAPI application setup
3. ✅ Database configuration
4. ✅ SQLAlchemy models
5. ✅ Alembic migrations
6. ✅ Pydantic schemas
7. ✅ Testing and documentation

See [Phase 1 tracking issue](https://github.com/Kickoman/rain-analysis/issues/223) for details.

### Phase 2: Authentication & API Key Management ✅ (Completed)

Phase 2 implemented secure API access:

1. ✅ API key database models
2. ✅ Authentication tables migration
3. ✅ API key generation and validation utilities
4. ✅ Rate limiting middleware
5. ✅ Admin endpoints for key management
6. ✅ Public authentication endpoints
7. ✅ Documentation and comprehensive testing

See [Phase 2 tracking issue](https://github.com/Kickoman/rain-analysis/issues/225) for details.

### Phase 3: Models Integration & Predictions API 🔄 (In Progress)

Phase 3 focuses on integrating ML models into the backend:

1. ✅ Database schema for models (#301)
2. ✅ Model loader and cache (#302)
3. ✅ Predictions service (#303)
4. ✅ Models API endpoints (#304)
5. ✅ Predictions API endpoints (#305)
6. ✅ Admin endpoints for model management (#306)
7. 🔄 Background task for daily ML analysis (#307)
8. 🔄 Phase 3 testing and documentation (#308)

See [Phase 3 tracking issue](https://github.com/Kickoman/rain-analysis/issues/231) for details.

### Phase 4: Reports API & History Migration 📋 (Planned)

Migration of historical reports and implementation of reports API.

See [Phase 4 tracking issue](https://github.com/Kickoman/rain-analysis/issues/232) for details.

### Phase 5: Frontend — Dashboard & Model Pages 📋 (Planned)

Web dashboard for visualizing model performance and predictions.

See [Phase 5 tracking issue](https://github.com/Kickoman/rain-analysis/issues/233) for details.

### Phase 6: Deployment & Infrastructure 📋 (Planned)

Production deployment setup and infrastructure configuration.

See [Phase 6 tracking issue](https://github.com/Kickoman/rain-analysis/issues/234) for details.

### Phase 7: Legacy Compatibility & Migration 📋 (Planned)

Migration from GitHub Pages to the new backend system.

See [Phase 7 tracking issue](https://github.com/Kickoman/rain-analysis/issues/235) for details.

## Requirements

- Python 3.11+
- pip

## License

MIT
