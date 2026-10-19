"""Owns the local SQLite engine and connection lifecycle."""

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import database_url


def create_database_engine() -> Engine:
    url = database_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    if url.startswith("sqlite:///") and ":memory:" not in url:
        from pathlib import Path

        database_path = Path(url.removeprefix("sqlite:///"))
        database_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)


engine = create_database_engine()


def check_database() -> None:
    """Execute a real SQL statement so health reports database connectivity."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
