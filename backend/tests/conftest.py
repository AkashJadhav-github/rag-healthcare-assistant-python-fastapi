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

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://healthcare_user:healthcare_pass@localhost:5432/healthcare_rag_test",
)

test_engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
TestSession = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
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


@pytest_asyncio.fixture
async def admin_user(db: AsyncSession) -> User:
    user = User(
        email="admin@test.com",
        username="testadmin",
        hashed_password=hash_password("Admin@12345!"),
        full_name="Test Admin",
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def clinician_user(db: AsyncSession) -> User:
    user = User(
        email="clinician@test.com",
        username="testclinician",
        hashed_password=hash_password("Clinic@12345!"),
        full_name="Test Clinician",
        role=UserRole.CLINICIAN,
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
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
