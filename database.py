"""Database engine and session factory.

The connection string comes from DATABASE_URL so the same code runs against
SQLite locally and Postgres in production. load_dotenv() is called here rather
than relying on main.py: this module is imported at the top of main.py, before
main.py's own load_dotenv() runs, so without it a .env-supplied DATABASE_URL
would be read too late and silently ignored.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./urls.db")

def engine_options(url: str) -> dict:
    """Per-backend create_engine() arguments.

    SQLite needs check_same_thread disabled because FastAPI serves sync
    handlers from a thread pool, and an in-memory database additionally needs
    every connection to be the same one — a fresh connection would open a
    separate empty database and see no schema at all. Postgres needs neither,
    and passing SQLite's arguments to it raises on connect.
    """
    if not url.startswith("sqlite"):
        return {}

    options = {"connect_args": {"check_same_thread": False}}
    if ":memory:" in url:
        options["poolclass"] = StaticPool
    return options


engine = create_engine(DATABASE_URL, **engine_options(DATABASE_URL))

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    """Yield a session and always close it.

    A FastAPI dependency rather than a SessionLocal() call in each handler:
    one place to change when pooling, retries or a read replica arrive, and no
    way to forget the try/finally.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
