"""Project paths and local settings; environment overrides stay process-local."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[4]
WEB_DIST = PROJECT_ROOT / "apps" / "web" / "dist"
SOURCE_INVENTORY = PROJECT_ROOT / "docs" / "source-inventory.json"
DEFAULT_DATABASE = PROJECT_ROOT / ".data" / "practice.sqlite3"
DEFAULT_LIBRARY_DIR = PROJECT_ROOT / ".data" / "library"
DEFAULT_BACKUP_DIR = PROJECT_ROOT / ".data" / "backups"
load_dotenv(PROJECT_ROOT / ".env")


def database_url() -> str:
    """Return an explicit local SQLite URL, or a caller-supplied URL."""
    configured = os.environ.get("TOEIC_DATABASE_URL")
    if configured:
        from sqlalchemy.engine import make_url

        url = make_url(configured)
        if url.get_backend_name() != "sqlite":
            raise ValueError("TOEIC_DATABASE_URL must use SQLite.")
        if url.database and url.database != ":memory:":
            database_path = Path(url.database)
            if not database_path.is_absolute():
                database_path = PROJECT_ROOT / database_path
            url = url.set(database=str(database_path.resolve()))
        return url.render_as_string(hide_password=False)
    return f"sqlite:///{DEFAULT_DATABASE.as_posix()}"


def library_dir() -> Path:
    configured = os.environ.get("TOEIC_LIBRARY_DIR")
    if configured:
        return Path(configured).resolve()
    for pool in (PROJECT_ROOT / '.data' / 'question-pool', PROJECT_ROOT / 'content' / 'question-pool'):
        if (pool / 'manifest.json').is_file():
            return pool
    return DEFAULT_LIBRARY_DIR


def backup_dir() -> Path:
    configured = os.environ.get("TOEIC_BACKUP_DIR")
    return Path(configured).resolve() if configured else DEFAULT_BACKUP_DIR
