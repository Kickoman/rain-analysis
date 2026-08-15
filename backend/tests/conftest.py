import os
import sys
from pathlib import Path

# Add backend directory to path for imports
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Set test environment variables before any imports
# Use a 64-character hex string (32 bytes) for testing
os.environ["API_KEYS_SALT"] = "a" * 64
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import pytest
import asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.database import Base, get_db
from app.main import app as _app
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def app():
    """Provide the FastAPI app instance."""
    return _app


@pytest.fixture
async def db_session():
    """Create in-memory test database session."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session() as session:
        yield session
    
    await engine.dispose()


@pytest.fixture
async def client(app, db_session: AsyncSession, monkeypatch):
    """Create test client with database override."""
    
    async def override_get_db():
        yield db_session
    
    # Override the dependency
    app.dependency_overrides[get_db] = override_get_db
    
    # Mock AsyncSessionLocal to return a context manager that yields the test session
    mock_session_maker = MagicMock()
    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__.return_value = db_session
    mock_context_manager.__aexit__.return_value = None
    mock_session_maker.return_value = mock_context_manager
    
    monkeypatch.setattr('app.auth.middleware.AsyncSessionLocal', mock_session_maker)
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
    
    app.dependency_overrides.clear()


@pytest.fixture
async def admin_api_key(db_session: AsyncSession):
    """Create an admin-scope API key; returns the raw key value."""
    from app.auth.crypto import generate_api_key
    from app.models.api_key import APIKey

    key_value, key_hash, key_prefix = generate_api_key()
    api_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner="test-admin",
        description="Test admin key",
        scope="admin",
        rate_limit_rpm=1000,
        rate_limit_rph=10000,
        rate_limit_rpd=100000,
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.commit()
    return key_value


@pytest.fixture
async def read_api_key(db_session: AsyncSession):
    """Create a read-scope API key; returns the raw key value."""
    from app.auth.crypto import generate_api_key
    from app.models.api_key import APIKey

    key_value, key_hash, key_prefix = generate_api_key()
    api_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner="test-read",
        description="Test read key",
        scope="read",
        rate_limit_rpm=1000,
        rate_limit_rph=10000,
        rate_limit_rpd=100000,
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.commit()
    return key_value
