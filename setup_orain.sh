#!/usr/bin/env bash
#
# setup_orain.sh — recreates the Orain project (Phase 1).
# Save this file into /Users/callummaclellan/Orain and run:  bash setup_orain.sh
#
set -e

# Work in the folder this script lives in, wherever that is.
cd "$(dirname "$0")"
echo "Setting up Orain in: $(pwd)"

mkdir -p backend data/users static

cat > "requirements.txt" << 'ORAIN_FILE_EOF'
# Òrain — runtime dependencies
#
# Deliberately minimal, following the Ceòl lessons:
#   - raw sqlite3 (stdlib), so NO SQLAlchemy
#   - bcrypt used directly, so NO passlib
#     (passlib 1.7.4 breaks against bcrypt 5.x on Python 3.13 — it reads
#      _bcrypt.__about__.__version__, which no longer exists)

fastapi>=0.110
uvicorn[standard]>=0.27
bcrypt>=4.0.0
ORAIN_FILE_EOF

cat > "README.md" << 'ORAIN_FILE_EOF'
# Òrain

A multi-user app for keeping a personal library of songs in Gàidhlig and
Beurla. Each user curates their own library; admin is about operating the
app, not co-owning anyone's songs.

## Stack

FastAPI + raw `sqlite3` (parameterised queries), vanilla JS frontend. No
SQLAlchemy, no templating engine, no passlib — inherited from Ceòl, kept
small on purpose.

## Project layout

```
orain/
  backend/
    __init__.py
    config.py     paths, env vars, cookie settings
    schema.py     schema as incremental migration lists (auth + library)
    db.py         contextvar, connection factories, _migrate()
    main.py       FastAPI app entry point
  data/
    users.db          shared auth database (created on first run)
    users/{id}/orain.db   one library database per user
  static/         vanilla-JS frontend (Phase 4)
  requirements.txt
```

## Multi-user model

Isolation is **by file**, not by a `WHERE` clause. There is no `user_id`
column on `songs` or `song_versions`. Each request resolves its user into
the `current_user_id` contextvar; the `_db()` connection factory reads that
contextvar to open the right `orain.db`. A buggy "return all rows" query
cannot leak across users — there is nothing to leak into.

The shared `users.db` holds auth only: `users`, `sessions`, `invites`,
`password_resets`.

## Schema migrations

Both databases version themselves via SQLite's `PRAGMA user_version`. To
change the schema, append a new list of statements to `AUTH_MIGRATIONS` or
`LIBRARY_MIGRATIONS` in `schema.py` — never edit a migration that has
already shipped. `db._migrate()` applies whatever is pending.

## Running

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

On startup the app creates `data/`, `static/`, and migrates `users.db`.
Check it is alive at <http://localhost:8000/health>.

## Build status

Phase 1 (Foundations) complete: project scaffold, pinned dependencies,
`users.db` and `orain.db` schemas, incremental `_migrate()`, and the `_db()`
connection factory. Phase 2 (auth and multi-user) is next.
ORAIN_FILE_EOF

cat > ".gitignore" << 'ORAIN_FILE_EOF'
# Python
__pycache__/
*.py[cod]
.venv/
venv/
*.egg-info/

# Runtime data — keep the directory structure, ignore the databases
data/users.db
data/users.db-journal
data/users.db-wal
data/users.db-shm
data/users/*/
data/seed/
!data/users/.gitkeep
ORAIN_FILE_EOF

cat > "backend/__init__.py" << 'ORAIN_FILE_EOF'
"""Òrain backend package."""
ORAIN_FILE_EOF

cat > "backend/config.py" << 'ORAIN_FILE_EOF'
"""Òrain — paths and configuration.

Everything that depends on *where* things live on disk, or on environment
variables, is centralised here so the rest of the backend can stay ignorant
of the filesystem layout.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------------
# BASE_DIR is the project root (the parent of backend/).
BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
USERS_DIR = DATA_DIR / "users"          # per-user library files live under here
SEED_DIR = DATA_DIR / "seed"            # optional starter corpus (data/seed/orain.db)
STATIC_DIR = BASE_DIR / "static"

# The shared auth database: users, sessions, invites, password_resets.
AUTH_DB_PATH = DATA_DIR / "users.db"

# ---------------------------------------------------------------------------
# Session cookie
# ---------------------------------------------------------------------------
# 90-day Max-Age so the cookie survives a PWA close/reopen on iOS.
SESSION_COOKIE_NAME = "orain_session"
SESSION_MAX_AGE = 90 * 24 * 60 * 60     # seconds

# ---------------------------------------------------------------------------
# Initial admin bootstrap
# ---------------------------------------------------------------------------
# If set, startup will ensure an admin account exists for this email,
# prompting for a password on first boot. Wired up fully in Phase 2.
ORAIN_INITIAL_ADMIN = os.environ.get("ORAIN_INITIAL_ADMIN")


def user_db_path(user_id: int) -> Path:
    """Return the path to a given user's personal library database.

    Each user's songs live in their own file — isolation is by file, not by
    a WHERE clause, so a buggy "return all rows" query cannot leak across
    users by construction.
    """
    return USERS_DIR / str(user_id) / "orain.db"


def ensure_dirs() -> None:
    """Create the data and static directories if they do not yet exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    USERS_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
ORAIN_FILE_EOF

cat > "backend/schema.py" << 'ORAIN_FILE_EOF'
"""Òrain — database schema, expressed as incremental migrations.

There are two independent migration sequences:

  * AUTH_MIGRATIONS    -> applied to the shared data/users.db
  * LIBRARY_MIGRATIONS -> applied to every per-user data/users/{id}/orain.db

Each sequence is a list. Element N is "migration N+1": a list of single SQL
statements to run to move the database from schema version N to version N+1.
The current version of any database is tracked by SQLite's own
`PRAGMA user_version`, so no bookkeeping table is needed.

To evolve the schema later, append a new list of statements to the relevant
sequence — never edit a migration that has already shipped, because existing
databases have already run it. db._migrate() applies whatever is pending.
"""

# ---------------------------------------------------------------------------
# Auth database (data/users.db) — shared across all users
# ---------------------------------------------------------------------------

AUTH_MIGRATIONS: list[list[str]] = [
    # --- migration 1: initial auth schema -----------------------------------
    [
        """
        CREATE TABLE users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            email         TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name  TEXT,
            is_admin      INTEGER NOT NULL DEFAULT 0,
            is_disabled   INTEGER NOT NULL DEFAULT 0,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE sessions (
            token      TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL
        )
        """,
        "CREATE INDEX idx_sessions_user ON sessions(user_id)",
        """
        CREATE TABLE invites (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            token            TEXT UNIQUE NOT NULL,
            email            TEXT,
            created_by       INTEGER REFERENCES users(id),
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at       TIMESTAMP,
            accepted_at      TIMESTAMP,
            accepted_user_id INTEGER REFERENCES users(id)
        )
        """,
        """
        CREATE TABLE password_resets (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            token      TEXT UNIQUE NOT NULL,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            used_at    TIMESTAMP
        )
        """,
    ],
]

# ---------------------------------------------------------------------------
# Library database (data/users/{id}/orain.db) — one per user
# ---------------------------------------------------------------------------
# Note: NO user_id column anywhere. Isolation is per-file. The two-table
# songs/song_versions split avoids Ceòl's empty-container parent rows and the
# type-filter bug class that came with them.

LIBRARY_MIGRATIONS: list[list[str]] = [
    # --- migration 1: initial library schema --------------------------------
    [
        """
        CREATE TABLE songs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            slug         TEXT UNIQUE NOT NULL,        -- for /songs/{slug}
            title        TEXT NOT NULL,
            composer     TEXT,
            rating       INTEGER,
            is_favourite INTEGER DEFAULT 0,
            on_hitlist   INTEGER DEFAULT 0,
            notes        TEXT,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE song_versions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            song_id       INTEGER NOT NULL REFERENCES songs(id),
            version_label TEXT,
            language      TEXT NOT NULL,              -- 'gd' | 'en'
            lyrics        TEXT,
            melody        TEXT,                       -- ABC or other notation
            source        TEXT,
            contributor   TEXT,
            transpose     INTEGER DEFAULT 0,
            is_canonical  INTEGER NOT NULL DEFAULT 0,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX idx_song_versions_song ON song_versions(song_id)",
    ],
]
ORAIN_FILE_EOF

cat > "backend/db.py" << 'ORAIN_FILE_EOF'
"""Òrain — database access layer.

The whole multi-user story lives here, and it is deliberately small:

  * `current_user_id` is a contextvar set once per request (by the session
    middleware, added in Phase 2). It is the *only* thing that selects which
    user's library a connection opens.

  * `_db()` is the library connection factory. It reads `current_user_id`
    and opens that user's `orain.db`. No endpoint ever needs to mention a
    user id — the request context already carries it.

  * `auth_db()` is the connection factory for the shared `users.db`.

Commit behaviour — note the deliberate asymmetry:

  * `auth_db()` does **not** auto-commit. Auth writes (session INSERTs in
    particular) need an explicit `conn.commit()`, or they roll back silently
    when the connection closes. This cost an evening in Ceòl; it is kept on
    purpose so that auth writes stay an explicit, conscious act.

  * `_db()` *does* auto-commit on a clean exit, because ordinary library
    edits are frequent and a forgotten commit there is just friction.
"""

import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from . import config, schema

# ---------------------------------------------------------------------------
# Request-scoped current user
# ---------------------------------------------------------------------------
# Resolved once per request by the session middleware (Phase 2). Until then
# it stays None, and calling _db() will raise rather than guess.
current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)


# ---------------------------------------------------------------------------
# Low-level connection helper
# ---------------------------------------------------------------------------

def _connect(path) -> sqlite3.Connection:
    """Open a SQLite connection with Òrain's standard pragmas.

    * `row_factory = sqlite3.Row` so rows are addressable by column name.
    * `foreign_keys = ON` — SQLite leaves FK enforcement off per-connection
      by default, so it must be switched on every time.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Incremental migrations
# ---------------------------------------------------------------------------

def _migrate(conn: sqlite3.Connection, migrations: list[list[str]]) -> int:
    """Bring `conn`'s database up to the latest schema version.

    Uses `PRAGMA user_version` as the stored version number. Applies every
    migration whose index is >= the current version, bumping the version
    after each one. A fresh database starts at version 0 and ends up at
    `len(migrations)`. Returns the resulting version.

    Idempotent: running it again on an up-to-date database does nothing.
    """
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    target = len(migrations)

    for version in range(current, target):
        for statement in migrations[version]:
            conn.execute(statement)
        # PRAGMA cannot be parameterised; version+1 is an int we control.
        conn.execute(f"PRAGMA user_version = {version + 1}")

    conn.commit()
    return target


# ---------------------------------------------------------------------------
# Database initialisation
# ---------------------------------------------------------------------------

def init_auth_db() -> None:
    """Create / migrate the shared auth database (data/users.db)."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connect(config.AUTH_DB_PATH)
    try:
        _migrate(conn, schema.AUTH_MIGRATIONS)
    finally:
        conn.close()


def init_library_db(user_id: int):
    """Create / migrate a single user's library database.

    Called when provisioning a new account (the invite-accept flow, Phase 2).
    Safe to call on an existing library — it simply applies any pending
    migrations. Returns the path to the database file.
    """
    path = config.user_db_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(path)
    try:
        _migrate(conn, schema.LIBRARY_MIGRATIONS)
    finally:
        conn.close()
    return path


# ---------------------------------------------------------------------------
# Connection factories
# ---------------------------------------------------------------------------

@contextmanager
def auth_db() -> Iterator[sqlite3.Connection]:
    """Connection to the shared auth database.

    Does NOT auto-commit — call `conn.commit()` explicitly after any write.
    """
    conn = _connect(config.AUTH_DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    """Connection to the *current user's* library database.

    The user is taken from the `current_user_id` contextvar — never passed
    in. Auto-commits on a clean exit; rolls back if the block raises.

    Raises RuntimeError if no user is in context (a programming error: an
    endpoint touched the library before the session middleware ran).
    """
    user_id = current_user_id.get()
    if user_id is None:
        raise RuntimeError(
            "_db() called with no current user in context — "
            "the session middleware must resolve a user first."
        )

    path = config.user_db_path(user_id)
    if not path.exists():
        # Opening a missing file would silently create an empty, unmigrated
        # database. A user's library is provisioned explicitly at invite-
        # accept time, so a missing file here is a real error.
        raise RuntimeError(f"No library database for user {user_id} at {path}")

    conn = _connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
ORAIN_FILE_EOF

cat > "backend/main.py" << 'ORAIN_FILE_EOF'
"""Òrain — FastAPI application entry point.

Phase 1 keeps this deliberately thin: it wires up the app, makes sure the
data directories exist, and migrates the shared auth database on startup.
Auth, session middleware, and the songs/versions API arrive in later phases.

Run locally from the project root with:

    uvicorn backend.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config, db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: ensure directories exist and the auth database is migrated."""
    config.ensure_dirs()
    db.init_auth_db()
    yield
    # Nothing to tear down — SQLite connections are opened and closed per use.


app = FastAPI(title="Òrain", lifespan=lifespan)

# Serve the (currently empty) static directory; the vanilla-JS frontend
# lands here in Phase 4.
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.get("/health")
def health() -> dict:
    """Lightweight liveness check — also confirms the app booted cleanly."""
    return {"status": "ok", "app": "orain"}
ORAIN_FILE_EOF

touch "data/users/.gitkeep"
touch "static/.gitkeep"

echo ""
echo "Done. Project structure created:"
find . -type f -not -path './.git/*' | sort | sed 's/^/  /'
echo ""
echo "Next steps:"
echo "  python3 -m venv .venv"
echo "  source .venv/bin/activate"
echo "  pip install -r requirements.txt"
echo "  uvicorn backend.main:app --reload"
