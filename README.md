# Rain Analysis

Прогнозирование дождя на основе данных с датчиков.

## Project Structure

```
rain-analysis/
├── backend/        # FastAPI web application
│   ├── app/        # Application code
│   │   ├── models/      # SQLAlchemy ORM models
│   │   ├── schemas/     # Pydantic validation schemas
│   │   ├── database.py  # Database setup
│   │   ├── config.py    # Configuration
│   │   └── main.py      # FastAPI application
│   ├── alembic/    # Database migrations
│   ├── tests/      # Backend tests
│   └── scripts/    # Utility scripts
├── ml/             # Machine learning models (legacy)
│   ├── notebooks/  # Jupyter notebooks
│   ├── training/   # Training scripts
│   └── tests/      # ML tests
├── scripts/        # Data processing utilities (legacy)
├── scripts_utils/  # Shared utilities
├── tests/          # Legacy test suite
└── docs/           # Documentation
```

## Quick Start

### Backend

```bash
cd backend

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and set API_KEYS_SALT

# Run database migrations
alembic upgrade head

# Start development server
python run.py
```

API documentation: http://localhost:8000/docs

### ML Training (Legacy)

```bash
# Install dependencies
pip install pandas numpy matplotlib jupyter

# Run analysis
cd ml
python training/train.py
```

See legacy [README](docs/legacy/README.md) for historical documentation.

## Development

### Running Tests

```bash
# Backend tests
cd backend
pytest -v

# Legacy ML tests
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

### Database Schema

The backend uses a flexible schema designed for multiple sensors and ML models:

- **sensors** - Sensor definitions (name, type, unit)
- **measurements** - Time-series sensor data
- **models** - ML model metadata
- **predictions** - Model predictions over time
- **model_metrics** - Model performance metrics

See [docs/architecture.md](docs/architecture.md) for detailed architecture documentation.

## Tech Stack

### Backend
- **FastAPI** - Modern Python web framework
- **SQLAlchemy 2.0** - Async ORM
- **Alembic** - Database migrations
- **Pydantic** - Data validation
- **SQLite/aiosqlite** - Database (development)

### Testing
- **pytest** - Test framework
- **pytest-asyncio** - Async test support
- **httpx** - HTTP client for testing

## Documentation

- [Architecture](docs/architecture.md) - System architecture overview
- [API Documentation](http://localhost:8000/docs) - Interactive API docs (when running)
- [Contributing](docs/CONTRIBUTING.md) - Development guidelines
- [Legacy Documentation](docs/legacy/) - Historical ML/analysis docs

## Phase 1: Backend Foundation (Completed)

Phase 1 focused on establishing the backend infrastructure:

1. ✅ Project restructuring
2. ✅ FastAPI application setup
3. ✅ Database configuration
4. ✅ SQLAlchemy models
5. ✅ Alembic migrations
6. ✅ Pydantic schemas
7. ✅ Testing and documentation

See [Phase 1 tracking issue](https://github.com/Kickoman/rain-analysis/issues/223) for details.

## Requirements

- Python 3.11+
- pip

## License

MIT
