# backend/app/core/db.py
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    """FastAPI dependency: yields sync SQLAlchemy Session and closes it after request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Ensure model modules are imported so SQLAlchemy can resolve relationships
import app.models  # noqa: F401
