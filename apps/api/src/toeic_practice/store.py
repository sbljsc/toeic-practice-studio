"""Transactional SQLite state store.

Attempts are immutable snapshots plus mutable live state; every mutation runs
inside BEGIN IMMEDIATE so concurrent writers serialize and a deadline check +
save + submit is atomic. History rows are never updated in place.
"""

import json
import sqlite3
import threading
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    scope TEXT NOT NULL,
    mode TEXT NOT NULL,
    original_mode TEXT NOT NULL,
    status TEXT NOT NULL,
    phase TEXT NOT NULL,
    integrity TEXT NOT NULL,
    created_at TEXT NOT NULL,
    closed_at TEXT,
    close_reason TEXT,
    exam_ids TEXT NOT NULL,
    parts TEXT NOT NULL,
    question_count INTEGER NOT NULL,
    current_index INTEGER NOT NULL DEFAULT 0,
    timer TEXT NOT NULL,
    questions TEXT NOT NULL,
    groups TEXT NOT NULL,
    question_exam TEXT NOT NULL,
    audio_queue TEXT NOT NULL,
    media_state TEXT,
    owner_tab_id TEXT,
    interruptions TEXT NOT NULL DEFAULT '[]',
    library_version TEXT NOT NULL,
    history_summary TEXT,
    report TEXT
);
CREATE TABLE IF NOT EXISTS answers (
    attempt_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    option_id TEXT,
    flagged INTEGER NOT NULL DEFAULT 0,
    visited INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (attempt_id, question_id)
);
CREATE TABLE IF NOT EXISTS mutations (
    mutation_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    attempt_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    causes TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (attempt_id, question_id)
);
CREATE TABLE IF NOT EXISTS vocab_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL,
    sense TEXT NOT NULL,
    modality TEXT NOT NULL,
    canonical_id TEXT NOT NULL,
    exam_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    cycle INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    library_version TEXT NOT NULL DEFAULT '',
    context TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vocab_key ON vocab_evidence(term, sense, modality, cycle, active);
CREATE TABLE IF NOT EXISTS vocab_state (
    term TEXT NOT NULL,
    sense TEXT NOT NULL,
    modality TEXT NOT NULL,
    mastered INTEGER NOT NULL DEFAULT 0,
    manual_required INTEGER NOT NULL DEFAULT 0,
    cycle INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (term, sense, modality)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS question_latest (
    canonical_id TEXT NOT NULL,
    library_version TEXT NOT NULL,
    state TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (canonical_id, library_version)
);
"""


class Store:
    """Owns the SQLite connection; a process-local lock wraps transactions."""

    def __init__(self, path) -> None:
        self.path = str(path)
        self.memory = self.path in (":memory:", "")
        if not self.memory:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False
        self._connect()

    def _connect(self) -> None:
        self._conn = sqlite3.connect(self.path or ":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA)
            columns = {r[1] for r in self._conn.execute("PRAGMA table_info(mutations)")}
            if "request_json" not in columns:
                self._conn.execute("ALTER TABLE mutations ADD COLUMN request_json TEXT")
            columns = {r[1] for r in self._conn.execute("PRAGMA table_info(attempts)")}
            if "activity" not in columns:
                # Additive v1 migration: old attempts remain explicitly unknown.
                self._conn.execute("ALTER TABLE attempts ADD COLUMN activity TEXT")
            row = self._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),)
                )
            elif int(row["value"]) != SCHEMA_VERSION:
                raise RuntimeError(f"数据库 schema 版本 {row['value']} 与本应用不一致")
            self._conn.commit()

    def transaction(self):
        return _Transaction(self)

    def query(self, sql: str, params: tuple = ()) -> list:
        with self._lock:
            if self._closed:
                raise RuntimeError("数据库连接已关闭（还原进行中）。")
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple = ()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()
            self._closed = True

    def reconnect(self) -> None:
        """Re-open the SQLite file after an exclusive file-level operation."""
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._closed = False
            self._connect()

    def checkpoint_and_close(self) -> None:
        """Flush WAL into the main file and close, releasing file handles so
        an exclusive restore can swap the database file on Windows."""
        with self._lock:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
            self._conn.close()
            self._closed = True

    def exclusive(self):
        """Hold the store lock across a multi-step file operation."""
        return self._lock

    def preserve_clock_transition(self, conn) -> None:
        """A rejected user mutation must retain the authoritative clock work.

        The savepoint is set before user writes. ApiError rolls those writes
        back while retaining only the preceding expiry/checkpoint transaction.
        Unexpected failures still roll back the entire transaction.
        """
        conn.execute("SAVEPOINT authoritative_clock")
        self._clock_savepoint = True


class _Transaction:
    def __init__(self, store: Store) -> None:
        self.store = store

    def __enter__(self) -> sqlite3.Connection:
        self.store._lock.acquire()
        try:
            conn = self.store._conn
            conn.execute("BEGIN IMMEDIATE")
            self.store._clock_savepoint = False
            return conn
        except BaseException:
            self.store._lock.release()
            raise

    def __exit__(self, exc_type, exc, tb) -> bool:
        conn = self.store._conn
        try:
            if exc_type is None:
                conn.commit()
            else:
                from .errors import ApiError
                if isinstance(exc, ApiError) and self.store._clock_savepoint:
                    conn.execute("ROLLBACK TO authoritative_clock")
                    conn.commit()
                else:
                    conn.rollback()
        finally:
            self.store._lock.release()
        return False


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(raw: str):
    return json.loads(raw)
