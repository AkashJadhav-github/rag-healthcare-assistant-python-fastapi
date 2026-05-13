import os
from typing import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

os.environ["ENVIRONMENT"] = "test"
os.environ["POSTGRES_DB"] = "healthcare_rag_test"
os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only-32chars"

from app.core.security import create_access_token, hash_password
from app.db.database import Base, get_db
from app.main import app
from app.models.user import User, UserRole

_pg_host = os.getenv("POSTGRES_HOST", "localhost")
_pg_port = os.getenv("POSTGRES_PORT", "5432")
_pg_user = os.getenv("POSTGRES_USER", "healthcare_user")
_pg_pass = os.getenv("POSTGRES_PASSWORD", "healthcare_pass")
TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    f"postgresql+asyncpg://{_pg_user}:{_pg_pass}@{_pg_host}:{_pg_port}/healthcare_rag_test",
)

def _ensure_test_db() -> None:
    import asyncio
    import asyncpg

    async def _create():
        conn = await asyncpg.connect(
            user=_pg_user, password=_pg_pass, host=_pg_host, port=int(_pg_port), database="healthcare_rag"
        )
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = 'healthcare_rag_test'")
        if not exists:
            await conn.execute("CREATE DATABASE healthcare_rag_test")
        await conn.close()

    asyncio.get_event_loop().run_until_complete(_create())


_ensure_test_db()

test_engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
TestSession = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session")
async def init_test_db():
    from sqlalchemy import text

    async with test_engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db(init_test_db) -> AsyncGenerator[AsyncSession, None]:
    async with TestSession() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(scope="session")
async def admin_user(init_test_db) -> User:
    async with TestSession() as session:
        user = User(
            email="admin@test.com",
            username="testadmin",
            hashed_password=hash_password("Admin@12345!"),
            full_name="Test Admin",
            role=UserRole.ADMIN,
            is_active=True,
            is_verified=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


@pytest_asyncio.fixture(scope="session")
async def clinician_user(init_test_db) -> User:
    async with TestSession() as session:
        user = User(
            email="clinician@test.com",
            username="testclinician",
            hashed_password=hash_password("Clinic@12345!"),
            full_name="Test Clinician",
            role=UserRole.CLINICIAN,
            is_active=True,
            is_verified=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


@pytest_asyncio.fixture(scope="session")
async def admin_token(admin_user: User) -> str:
    return create_access_token(subject=str(admin_user.id))


@pytest_asyncio.fixture
async def clinician_token(clinician_user: User) -> str:
    return create_access_token(subject=str(clinician_user.id))


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
