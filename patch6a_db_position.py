#!/usr/bin/env python3
"""Add a nullable `series_position` column to collections, for ordering
chapters within a series. Idempotent, same pattern as the series_id add.

NULL = no manual position set yet (falls back to created_at in queries).

Run from ~/gshadow. Anchor must match exactly once; result must parse.
"""
import ast
import sys

PATH = "app/db.py"
text = open(PATH).read()

OLD = '''        if "series_id" not in existing_coll_cols:
            conn.execute(
                "ALTER TABLE collections ADD COLUMN series_id INTEGER "
                "REFERENCES series(id) ON DELETE SET NULL"
            )
        conn.commit()'''

NEW = '''        if "series_id" not in existing_coll_cols:
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
        conn.commit()'''

if text.count(OLD) != 1:
    sys.exit(f"ABORT: anchor matched {text.count(OLD)} times (expected 1). No file written.")
text = text.replace(OLD, NEW)
try:
    ast.parse(text)
except SyntaxError as e:
    sys.exit(f"ABORT: result has a syntax error: {e}. No file written.")
with open(PATH, "w") as f:
    f.write(text)
print(f"OK: wrote {PATH} — added series_position column migration")
