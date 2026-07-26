# Development Guide

This guide is for developers working on the Rain Analysis API codebase.

## Table of Contents

- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Authentication System](#authentication-system)
- [Database Migrations](#database-migrations)
- [Testing](#testing)
- [Code Style](#code-style)
- [Contributing](#contributing)

## Development Setup

### Prerequisites

- Python 3.11+
- pip
- Git

### Initial Setup

```bash
# Clone repository
git clone https://github.com/Kickoman/rain-analysis.git
cd rain-analysis

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
cd backend
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env and configure:
#   - API_KEYS_SALT (generate with: python -c "import secrets; print(secrets.token_urlsafe(32))")
#   - DATABASE_URL (optional, defaults to SQLite)

# Run migrations
alembic upgrade head

# Create admin key
python scripts/create_admin_key.py

# Run tests
pytest -v

# Start development server
python run.py
```

### Environment Variables

Create a `.env` file in `backend/` directory:

```bash
# Required
API_KEYS_SALT=your-secret-salt-here

# Optional
DATABASE_URL=sqlite+aiosqlite:///./rain_analysis.db
CORS_ORIGINS=["http://localhost:3000"]
LOG_LEVEL=INFO
```

## Project Structure

```
rain-analysis/
├── backend/
│   ├── app/
│   │   ├── auth/              # Authentication system
│   │   │   ├── crypto.py      # Key generation and hashing
│   │   │   ├── middleware.py  # Authentication middleware
│   │   │   └── rate_limiter.py # Rate limiting logic
│   │   ├── models/            # SQLAlchemy ORM models
│   │   │   ├── api_key.py     # API key model
│   │   │   ├── api_request_log.py  # Request tracking
│   │   │   ├── admin_audit_log.py  # Admin action audit
│   │   │   └── ...            # Data models
│   │   ├── routers/           # FastAPI route handlers
│   │   │   ├── admin.py       # Admin endpoints
│   │   │   └── auth.py        # Auth endpoints
│   │   ├── schemas/           # Pydantic validation schemas
│   │   │   ├── api_key.py     # API key schemas
│   │   │   └── ...
│   │   ├── config.py          # Configuration
│   │   ├── database.py        # Database setup
│   │   └── main.py            # FastAPI application
│   ├── alembic/               # Database migrations
│   ├── scripts/               # Utility scripts
│   │   └── create_admin_key.py
│   └── tests/                 # Test suite
│       ├── conftest.py        # Pytest fixtures
│       ├── test_auth_*.py     # Auth tests
│       └── ...
├── docs/                      # Documentation
└── ml/                        # Legacy ML code
```

## Authentication System

### Architecture Overview

The authentication system consists of several layers:

1. **API Keys** (`app/models/api_key.py`)
   - Stored in database with hashed values
   - Have scopes, rate limits, and expiration
   - Can be activated/deactivated

2. **Middleware** (`app/auth/middleware.py`)
   - Intercepts all requests
   - Validates API key
   - Checks scopes and rate limits
   - Attaches authenticated key to request state

3. **Rate Limiter** (`app/auth/rate_limiter.py`)
   - Tracks requests per key
   - Enforces RPM/RPH/RPD limits
   - Uses database-backed counters

4. **Crypto Utilities** (`app/auth/crypto.py`)
   - Generates secure API keys
   - Hashes keys for storage
   - Verifies keys

### How Authentication Middleware Works

```python
# Simplified flow in app/auth/middleware.py

async def auth_middleware(request: Request, call_next):
    # 1. Extract API key from X-API-Key header
    api_key = request.headers.get("X-API-Key")
    
    # 2. Validate key format
    if not api_key or not api_key.startswith("ra_live_"):
        return error_response(401, "Invalid API key")
    
    # 3. Hash and lookup in database
    key_hash = hash_api_key(api_key)
    db_key = await get_key_by_hash(key_hash)
    
    # 4. Check if key is active and not expired
    if not db_key or not db_key.is_active:
        return error_response(401, "Invalid API key")
    
    if db_key.expires_at and db_key.expires_at < datetime.utcnow():
        return error_response(401, "API key expired")
    
    # 5. Check rate limits
    rate_limit_check = await check_rate_limits(db_key)
    if not rate_limit_check.allowed:
        return error_response(429, "Rate limit exceeded")
    
    # 6. Check scope for endpoint
    required_scope = get_required_scope(request.url.path)
    if required_scope and required_scope not in db_key.scopes:
        return error_response(403, "Insufficient scope")
    
    # 7. Attach key to request state
    request.state.api_key = db_key
    
    # 8. Log request
    await log_request(db_key, request)
    
    # 9. Process request
    response = await call_next(request)
    
    # 10. Update last_used_at
    await update_last_used(db_key)
    
    return response
```

### Adding a New Scope

To add a new scope:

1. **Define the scope name** in your router:

```python
# backend/app/routers/data_ingestion.py
from fastapi import APIRouter, Request, HTTPException

router = APIRouter(prefix="/ingest", tags=["Data Ingestion"])

@router.post("/measurements")
async def ingest_measurements(request: Request, data: MeasurementData):
    # Check scope
    api_key = request.state.api_key
    if "write" not in api_key.scopes:
        raise HTTPException(
            status_code=403,
            detail="This endpoint requires 'write' scope"
        )
    
    # Process data...
```

2. **Update middleware scope mapping** (if using path-based scope checks):

```python
# backend/app/auth/middleware.py

SCOPE_REQUIREMENTS = {
    "/admin": "admin",
    "/ingest": "write",
    "/data": "read",
}
```

3. **Document the scope** in [AUTHENTICATION.md](AUTHENTICATION.md):

```markdown
### Available Scopes

| Scope | Description | Access Level |
|-------|-------------|--------------|
| `read` | Read-only data access | GET endpoints |
| `write` | Data ingestion | POST/PUT/PATCH data endpoints |
| `ingest` | IoT device ingestion | POST /ingest/* |
| `admin` | Full administrative access | All endpoints |
```

### Modifying Rate Limiting Logic

Rate limits are enforced in `app/auth/rate_limiter.py`:

```python
class RateLimiter:
    async def check_rate_limit(
        self, 
        api_key: APIKey, 
        request_path: str
    ) -> RateLimitResult:
        """Check if request is allowed under rate limits."""
        
        now = datetime.utcnow()
        
        # Check RPM (requests per minute)
        if api_key.rate_limit_rpm:
            rpm_count = await self._count_requests(
                api_key.id, 
                since=now - timedelta(minutes=1)
            )
            if rpm_count >= api_key.rate_limit_rpm:
                return RateLimitResult(
                    allowed=False,
                    limit_type="rpm",
                    reset_at=self._next_minute()
                )
        
        # Check RPH and RPD similarly...
        
        return RateLimitResult(allowed=True)
```

**To add custom rate limiting:**

1. Add new limit field to `APIKey` model
2. Create migration: `alembic revision --autogenerate -m "Add custom rate limit"`
3. Update `RateLimiter.check_rate_limit()` logic
4. Add field to admin endpoints
5. Write tests

**Example: Add per-endpoint rate limits:**

```python
# New model field
class APIKey(Base):
    # ...existing fields...
    endpoint_rate_limits = Column(JSON, nullable=True)
    # Format: {"POST /ingest": {"rpm": 10}, "GET /data": {"rpm": 100}}

# Rate limiter logic
async def check_rate_limit(self, api_key: APIKey, request_path: str):
    # Check global limits first...
    
    # Then check endpoint-specific limits
    if api_key.endpoint_rate_limits:
        endpoint_key = f"{request.method} {request_path}"
        if endpoint_key in api_key.endpoint_rate_limits:
            endpoint_limits = api_key.endpoint_rate_limits[endpoint_key]
            # Check endpoint-specific limits...
```

### Key Generation and Hashing

Keys are generated in `app/auth/crypto.py`:

```python
def generate_api_key() -> str:
    """Generate a secure API key."""
    # Format: ra_live_<32 random bytes as base64url>
    random_bytes = secrets.token_bytes(32)
    key_part = base64.urlsafe_b64encode(random_bytes).decode().rstrip("=")
    return f"ra_live_{key_part}"

def hash_api_key(api_key: str) -> str:
    """Hash API key for storage."""
    # Use PBKDF2 with salt from environment
    from app.config import settings
    pwd_context = CryptContext(schemes=["pbkdf2_sha256"])
    return pwd_context.hash(api_key + settings.api_keys_salt)

def verify_api_key(api_key: str, key_hash: str) -> bool:
    """Verify API key against stored hash."""
    from app.config import settings
    pwd_context = CryptContext(schemes=["pbkdf2_sha256"])
    return pwd_context.verify(api_key + settings.api_keys_salt, key_hash)
```

**Security considerations:**

- **Salt is critical**: The `API_KEYS_SALT` must be kept secret and unique per environment
- **One-way hashing**: Keys are hashed, not encrypted - they cannot be recovered
- **Timing attacks**: Use constant-time comparison for key verification
- **Key rotation**: Support key rotation by allowing multiple active keys per user

### Audit Logging

All admin actions are logged in `admin_audit_logs` table:

```python
# Automatic logging in admin endpoints
async def create_api_key(request: Request, key_data: APIKeyCreate):
    # Create key...
    
    # Log action
    audit_entry = AdminAuditLog(
        api_key_id=request.state.api_key.id,
        action="create_key",
        target_key_id=new_key.id,
        details={
            "key_name": new_key.name,
            "scopes": new_key.scopes,
            "rate_limits": {
                "rpm": new_key.rate_limit_rpm,
                "rph": new_key.rate_limit_rph,
                "rpd": new_key.rate_limit_rpd
            }
        },
        created_at=datetime.utcnow()
    )
    db.add(audit_entry)
    await db.commit()
```

**Audit log actions:**
- `create_key` - New API key created
- `update_key` - API key modified
- `revoke_key` - API key deactivated
- `delete_key` - API key permanently deleted (if implemented)

## Database Migrations

### Creating Migrations

```bash
cd backend

# Auto-generate migration from model changes
alembic revision --autogenerate -m "Add new field to sensors"

# Create empty migration for manual changes
alembic revision -m "Add custom index"
```

### Migration Best Practices

1. **Review auto-generated migrations** - Alembic doesn't catch everything
2. **Test migrations** - Run upgrade/downgrade in development
3. **Add data migrations separately** - Don't mix schema and data changes
4. **Use batch operations** for SQLite compatibility:

```python
def upgrade():
    with op.batch_alter_table('api_keys') as batch_op:
        batch_op.add_column(sa.Column('new_field', sa.String(50)))
```

### Common Migration Patterns

**Add nullable column:**
```python
def upgrade():
    op.add_column('api_keys', sa.Column('description', sa.Text, nullable=True))

def downgrade():
    op.drop_column('api_keys', 'description')
```

**Add non-nullable column with default:**
```python
def upgrade():
    # SQLite requires batch mode
    with op.batch_alter_table('api_keys') as batch_op:
        batch_op.add_column(
            sa.Column('is_active', sa.Boolean, nullable=False, server_default='1')
        )

def downgrade():
    with op.batch_alter_table('api_keys') as batch_op:
        batch_op.drop_column('is_active')
```

## Testing

### Running Tests

```bash
cd backend

# Run all tests
pytest -v

# Run specific test file
pytest tests/test_auth_e2e.py -v

# Run with coverage
pytest --cov=app --cov-report=term-missing --cov-report=html

# Run tests matching pattern
pytest -k "test_rate_limit" -v
```

### Test Structure

Tests use pytest with async support:

```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_create_api_key(client: AsyncClient, admin_key):
    """Test API key creation."""
    response = await client.post(
        "/admin/keys",
        headers={"X-API-Key": admin_key},
        json={
            "name": "test-key",
            "scopes": ["read"],
            "rate_limit_rpm": 60
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "test-key"
    assert "key" in data
```

### Fixtures

Common fixtures are in `tests/conftest.py`:

- `client` - AsyncClient for API testing
- `db_session` - Database session
- `admin_key` - Admin API key for testing
- `read_key` - Read-only API key for testing

### Writing New Tests

1. **Create test file**: `tests/test_feature.py`
2. **Import fixtures**: `from conftest import client, db_session`
3. **Write test functions**: Prefix with `test_`
4. **Use async/await**: Mark with `@pytest.mark.asyncio`
5. **Assert behavior**: Use clear assertions with messages

**Example:**
```python
@pytest.mark.asyncio
async def test_rate_limit_enforcement(client, db_session):
    """Test that rate limits are properly enforced."""
    # Setup: create key with low RPM limit
    test_key = create_test_key(rate_limit_rpm=2)
    
    # Action: make requests until rate limited
    responses = []
    for i in range(5):
        response = await client.get(
            "/health",
            headers={"X-API-Key": test_key}
        )
        responses.append(response)
    
    # Assert: some requests should be rate limited
    success = [r for r in responses if r.status_code == 200]
    rate_limited = [r for r in responses if r.status_code == 429]
    
    assert len(success) <= 2, "Should not exceed RPM limit"
    assert len(rate_limited) > 0, "Should trigger rate limiting"
```

## Code Style

### Python Style

- Follow [PEP 8](https://pep8.org/)
- Use type hints
- Max line length: 100 characters
- Use async/await for database operations

### Formatting

```bash
# Format code with black
black backend/

# Sort imports with isort
isort backend/

# Lint with flake8
flake8 backend/
```

### Documentation

- Add docstrings to all public functions
- Use Google-style docstrings:

```python
async def create_api_key(key_data: APIKeyCreate) -> APIKey:
    """
    Create a new API key.
    
    Args:
        key_data: API key creation data including name, scopes, and rate limits
        
    Returns:
        Created API key instance with generated key value
        
    Raises:
        ValueError: If scopes are invalid
        DatabaseError: If database operation fails
    """
    # Implementation...
```

## Contributing

1. **Fork the repository**
2. **Create feature branch**: `git checkout -b feature/my-feature`
3. **Make changes**: Follow code style and add tests
4. **Run tests**: `pytest -v`
5. **Commit changes**: Use clear commit messages
6. **Push branch**: `git push origin feature/my-feature`
7. **Create Pull Request**: Describe changes and link related issues

### Commit Message Format

```
type(scope): short description

Longer description if needed.

Fixes #123
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `test`: Adding/updating tests
- `refactor`: Code refactoring
- `chore`: Maintenance tasks

**Examples:**
```
feat(auth): add API key expiration support

Implements expiration date checking in middleware.
Keys past their expiration date are rejected with 401.

Closes #234

---

fix(rate-limit): correct RPH counter reset time

The RPH counter was resetting at the wrong time due to
timezone handling. Now properly uses UTC.

Fixes #245
```

## Additional Resources

- [Architecture Documentation](architecture.md)
- [Authentication Guide](AUTHENTICATION.md)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.0 Documentation](https://docs.sqlalchemy.org/)
- [Pytest Documentation](https://docs.pytest.org/)
