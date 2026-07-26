# Architecture

## Overview

Репозиторий разделён на 3 основных части:

1. **backend/** - FastAPI веб-приложение
2. **ml/** - ML модели и обучение (legacy)
3. **scripts/** - Утилиты обработки данных (legacy)

## Backend Architecture

### Tech Stack

- **FastAPI** - Modern async web framework
- **SQLAlchemy 2.0** - Async ORM with declarative models
- **Alembic** - Database migrations
- **Pydantic** - Request/response validation
- **aiosqlite** - Async SQLite driver

### Database Schema

Гибкая схема с таблицами:

#### Core Tables

**sensors** - Определение датчиков
```sql
- id: INTEGER PRIMARY KEY
- name: VARCHAR(100) UNIQUE NOT NULL
- unit: VARCHAR(20)
- sensor_type: VARCHAR(50) NOT NULL
- description: TEXT
- metadata: JSON
- created_at: TIMESTAMP
```

**measurements** - Данные с датчиков
```sql
- id: INTEGER PRIMARY KEY
- sensor_id: INTEGER FK -> sensors.id
- timestamp: TIMESTAMP NOT NULL
- value: FLOAT NOT NULL
- quality: VARCHAR(20)
- metadata: JSON
- INDEX: (sensor_id, timestamp)
- INDEX: (timestamp)
```

**models** - ML модели
```sql
- id: INTEGER PRIMARY KEY
- name: VARCHAR(100) UNIQUE NOT NULL
- version: VARCHAR(50) NOT NULL
- model_type: VARCHAR(50) NOT NULL
- model_path: VARCHAR(500)
- metadata: JSON
- created_at: TIMESTAMP
```

**predictions** - Предсказания моделей
```sql
- id: INTEGER PRIMARY KEY
- model_id: INTEGER FK -> models.id
- timestamp: TIMESTAMP NOT NULL
- prediction_value: FLOAT NOT NULL
- confidence: FLOAT
- metadata: JSON
- created_at: TIMESTAMP
- INDEX: (model_id, timestamp)
- INDEX: (timestamp)
```

**model_metrics** - Метрики качества
```sql
- id: INTEGER PRIMARY KEY
- model_id: INTEGER FK -> models.id
- metric_name: VARCHAR(100) NOT NULL
- metric_value: FLOAT NOT NULL
- evaluation_period_start: TIMESTAMP
- evaluation_period_end: TIMESTAMP
- metadata: JSON
- created_at: TIMESTAMP
- INDEX: (model_id, metric_name)
```

### Design Principles

**Flexibility**: Generic sensor/measurement tables support any sensor type without schema changes.

**Extensibility**: JSON metadata fields allow custom attributes without migrations.

**Performance**: Indexes on frequently queried columns (sensor_id, timestamp, model_id).

**Scalability**: Async throughout - can handle concurrent requests efficiently.

### API Structure

```
/                   - API information
/health             - Health check endpoint
/docs               - Interactive API documentation (Swagger UI)
/openapi.json       - OpenAPI schema

Planned endpoints:
/api/v1/sensors/*       - Sensor CRUD operations
/api/v1/measurements/*  - Measurement ingestion & retrieval
/api/v1/models/*        - Model management
/api/v1/predictions/*   - Prediction API
/api/v1/metrics/*       - Metrics API
```

### Application Layers

```
┌─────────────────────────────────────┐
│   FastAPI Routes (main.py)          │
│   - Request validation              │
│   - Response serialization          │
└─────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│   Pydantic Schemas (schemas/)       │
│   - Input validation                │
│   - Output models                   │
└─────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│   SQLAlchemy Models (models/)       │
│   - ORM mapping                     │
│   - Relationships                   │
└─────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│   Database (SQLite + aiosqlite)     │
│   - Async operations                │
│   - Connection pooling              │
└─────────────────────────────────────┘
```

## Configuration

Environment-based configuration via `.env` file:

```bash
DATABASE_URL=sqlite+aiosqlite:///./rain_analysis.db
API_KEYS_SALT=your-secret-salt
CORS_ORIGINS=["http://localhost:3000"]
LOG_LEVEL=INFO
```

Configuration managed by `pydantic-settings` with validation.

## Testing Strategy

### Unit Tests
- Pydantic schema validation
- Database models
- Utility functions

### Integration Tests
- API endpoints (using TestClient)
- Database operations (in-memory SQLite)
- End-to-end flows

### Test Database
- In-memory SQLite for speed
- Isolated per-test session
- Automatic schema creation/teardown

## Migrations

Alembic manages database schema evolution:

```bash
# Create migration after model changes
alembic revision --autogenerate -m "Add new column"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1

# View history
alembic history
```

## Future Enhancements

### Phase 2 (Planned)
- CRUD endpoints for all resources
- Authentication & authorization
- Rate limiting
- Caching layer (Redis)

### Phase 3 (Planned)
- Real-time predictions via WebSocket
- Model training API
- Batch inference
- Model versioning & A/B testing

### Scalability Considerations
- PostgreSQL for production (replace SQLite)
- Connection pooling
- Query optimization
- Horizontal scaling with load balancer
- Separate read replicas

## Development Workflow

1. Make model changes in `backend/app/models/`
2. Create migration: `alembic revision --autogenerate -m "description"`
3. Review generated migration in `backend/alembic/versions/`
4. Apply migration: `alembic upgrade head`
5. Update schemas in `backend/app/schemas/`
6. Add tests in `backend/tests/`
7. Run tests: `pytest -v`

## Monitoring & Observability

### Current
- Health check endpoint
- Application logging (configurable level)
- FastAPI automatic docs

### Planned
- Structured logging (JSON)
- Metrics (Prometheus)
- Distributed tracing (OpenTelemetry)
- Error tracking (Sentry)

## Security Considerations

### Current
- CORS configuration
- Input validation via Pydantic
- SQL injection prevention (ORM)

### Planned
- API key authentication
- Rate limiting per client
- Request size limits
- SQL query timeouts
- Secrets management (environment variables)
