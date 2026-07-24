from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from .config import settings
import logging

logger = logging.getLogger(__name__)

# Async engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.log_level == "DEBUG",
    future=True
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False
)

# Base для моделей
Base = declarative_base()

# Dependency для FastAPI
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

# Инициализация БД
async def init_db():
    """Create all tables"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized")

# Закрытие подключений
async def close_db():
    """Close database connections"""
    await engine.dispose()
    logger.info("Database connections closed")
