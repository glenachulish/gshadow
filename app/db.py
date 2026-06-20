"""SQLite helpers: connection lifecycle and schema setup."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "gshadow.db"


def _open() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    # check_same_thread=False is safe here: each request gets its own
    # connection via the get_db() dependency, and we never share a
    # connection across requests. The flag is only needed because
    # FastAPI may run sync dependencies and async routes on different
    # threads within the SAME request.
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_db():
    """FastAPI dependency: yields a connection and closes it after the request."""
    conn = _open()
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they don't exist and run column migrations.
    Safe to call repeatedly. Idempotent."""
    conn = _open()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                email         TEXT    NOT NULL UNIQUE,
                password_hash TEXT    NOT NULL,
                role          TEXT    NOT NULL CHECK (role IN ('admin', 'uploader', 'viewer')),
                is_active     INTEGER NOT NULL DEFAULT 1,
                created_at    TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS clips (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                title        TEXT    NOT NULL,
                description  TEXT,
                advice       TEXT,
                filename     TEXT    NOT NULL UNIQUE,
                uploaded_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
                uploaded_at  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS collections (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                slug          TEXT    NOT NULL UNIQUE,
                title         TEXT    NOT NULL,
                description   TEXT,
                transcript    TEXT,
                notes         TEXT,
                source_url    TEXT,
                category      TEXT    NOT NULL DEFAULT 'other',
                uploaded_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at    TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS import_jobs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                url           TEXT    NOT NULL,
                status        TEXT    NOT NULL CHECK (status IN ('queued', 'running', 'done', 'failed')),
                message       TEXT,
                collection_id INTEGER REFERENCES collections(id) ON DELETE SET NULL,
                created_at    TEXT    NOT NULL,
                updated_at    TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS series (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                slug        TEXT    NOT NULL UNIQUE,
                title       TEXT    NOT NULL,
                description TEXT,
                category    TEXT    NOT NULL DEFAULT 'other',
                created_at  TEXT    NOT NULL
            );
            """
        )
        # Migrate clips table: add collection_id + position columns if missing.
        existing_clip_cols = {row["name"] for row in conn.execute("PRAGMA table_info(clips)")}
        if "collection_id" not in existing_clip_cols:
            conn.execute(
                "ALTER TABLE clips ADD COLUMN collection_id INTEGER "
                "REFERENCES collections(id) ON DELETE SET NULL"
            )
        if "position" not in existing_clip_cols:
            conn.execute("ALTER TABLE clips ADD COLUMN position INTEGER")
        # Migrate collections table: add category column if missing.
        # Backfill defaults: 'litir-bheag' if slug starts with that, 'litir' if
        # slug starts with 'litir-' (but not 'litir-bheag'), else 'other'.
        existing_coll_cols = {row["name"] for row in conn.execute("PRAGMA table_info(collections)")}
        if "category" not in existing_coll_cols:
            conn.execute(
                "ALTER TABLE collections ADD COLUMN category TEXT "
                "NOT NULL DEFAULT 'other'"
            )
            conn.execute(
                "UPDATE collections SET category = 'litir-bheag' "
                "WHERE slug LIKE 'litir-bheag-%'"
            )
            conn.execute(
                "UPDATE collections SET category = 'litir' "
                "WHERE slug LIKE 'litir-%' AND slug NOT LIKE 'litir-bheag-%'"
            )
        # Migrate collections table: add series_id column if missing.
        # Nullable FK to series(id); ON DELETE SET NULL so deleting a series
        # orphans its chapters back to loose collections rather than deleting
        # their audio. No backfill: every existing collection starts ungrouped.
        if "series_id" not in existing_coll_cols:
            conn.execute(
                "ALTER TABLE collections ADD COLUMN series_id INTEGER "
                "REFERENCES series(id) ON DELETE SET NULL"
            )
        # Migrate collections table: add series_position for manual chapter
        # ordering within a series. NULL = unset (queries fall back to
        # created_at). No backfill.
        if "series_position" not in existing_coll_cols:
            conn.execute(
                "ALTER TABLE collections ADD COLUMN series_position INTEGER"
            )
        conn.commit()
    finally:
        conn.close()
