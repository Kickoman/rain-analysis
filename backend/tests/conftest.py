import os

# Set test environment variables before any imports
os.environ["API_KEYS_SALT"] = "test-salt-for-testing"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import pytest
import asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from backend.app.database import Base, get_db
from backend.app.main import app
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


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
async def client(db_session: AsyncSession, monkeypatch):
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
    
    monkeypatch.setattr('backend.app.auth.middleware.AsyncSessionLocal', mock_session_maker)
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
    
    app.dependency_overrides.clear()
