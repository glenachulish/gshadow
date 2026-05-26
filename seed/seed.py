"""Seed the database from seed/manifest.yaml.

Run from the project root:
    python -m seed.seed

The manifest lists clips that should exist in the audio/ directory. Each
entry that has its file present and isn't already in the database gets
inserted. Idempotent — safe to run repeatedly after dropping new files in.
"""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Make `app` importable when running this as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import DB_PATH, init_db  # noqa: E402

MANIFEST = Path(__file__).parent / "manifest.yaml"
AUDIO_DIR = Path(__file__).resolve().parent.parent / "audio"


def main() -> int:
    if not MANIFEST.exists():
        print(f"No manifest at {MANIFEST}. Create one to seed clips.", file=sys.stderr)
        return 1

    init_db()

    with open(MANIFEST) as f:
        items = yaml.safe_load(f) or []

    conn = sqlite3.connect(str(DB_PATH))
    inserted = skipped = missing = 0
    for item in items:
        filename = item.get("filename")
        if not filename:
            print(f"  SKIP (no filename): {item!r}")
            continue
        audio_path = AUDIO_DIR / filename
        if not audio_path.exists():
            print(f"  MISSING file: {audio_path}")
            missing += 1
            continue
        exists = conn.execute(
            "SELECT 1 FROM clips WHERE filename = ?", (filename,)
        ).fetchone()
        if exists:
            skipped += 1
            continue
        conn.execute(
            "INSERT INTO clips (title, description, advice, filename, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                item.get("title", filename),
                item.get("description", ""),
                item.get("advice", ""),
                filename,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        inserted += 1
        print(f"  + {filename}: {item.get('title', '(untitled)')}")
    conn.commit()
    print(
        f"\nSeed complete: {inserted} inserted, {skipped} already present, "
        f"{missing} files missing."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
