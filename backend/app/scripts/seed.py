"""Seed default admin user on first startup."""
import os
from sqlalchemy import select
import structlog

logger = structlog.get_logger()


async def seed_admin_user():
    from ..db.database import AsyncSessionLocal
    from ..models.user import User, UserRole
    from ..core.security import hash_password

    admin_email = os.getenv("ADMIN_EMAIL", "admin@healthcare.local")
    admin_password = os.getenv("ADMIN_PASSWORD", "Admin@12345!")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == admin_email))
        if result.scalar_one_or_none():
            return

        admin = User(
            email=admin_email,
            username="admin",
            hashed_password=hash_password(admin_password),
            full_name="System Administrator",
            role=UserRole.ADMIN,
            is_active=True,
            is_verified=True,
        )
        db.add(admin)
        await db.commit()
        logger.info("admin_user_seeded", email=admin_email)
