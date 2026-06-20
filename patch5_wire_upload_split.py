#!/usr/bin/env python3
"""Restore the upload_split wiring that was dropped when main.py was rewritten.
Without it, _staging_root is None and /split 500s at upload
(TypeError: unsupported operand type(s) for /: 'NoneType' and 'str').

Adds, matching the original 155ad11 main.py:
  - `from . import upload_split` (alongside the other module imports)
  - `STAGING_DIR = ROOT / "data" / "staging"` (under data/, the only writable
    path under the systemd ProtectSystem=strict sandbox)
  - `upload_split.configure(DB_PATH, STAGING_DIR, AUDIO_DIR)` at startup
  - imports DB_PATH from .db

Run from ~/gshadow. Each anchor must match exactly once; result must parse.
"""
import ast
import sys

PATH = "app/main.py"
text = open(PATH).read()

EDITS = [
    # 1. Add the upload_split import next to the series import.
    (
        "Add upload_split import",
        "from . import collections as collections_module\nfrom . import series as series_module",
        "from . import collections as collections_module\nfrom . import series as series_module\nfrom . import upload_split",
    ),
    # 2. After the series router is wired, add the upload_split configure block.
    #    Anchor on the series wiring block (unique).
    (
        "Add upload_split.configure after series wiring",
        '''series_module.configure(templates)
app.include_router(series_module.router)''',
        '''series_module.configure(templates)
app.include_router(series_module.router)

# Wire the in-app split feature. Staging MUST live under data/ — the systemd
# service runs with ProtectSystem=strict and can only write to data/ and audio/.
from .db import DB_PATH
STAGING_DIR = ROOT / "data" / "staging"
upload_split.configure(DB_PATH, STAGING_DIR, AUDIO_DIR)''',
    ),
]

for desc, find, replace in EDITS:
    n = text.count(find)
    if n != 1:
        sys.exit(f"ABORT: edit '{desc}' matched {n} times (expected 1). No file written.")
    text = text.replace(find, replace)

# Confirm DB_PATH is importable from db (the original imported it; verify the
# name exists in db.py so the import won't fail at runtime).
try:
    db_src = open("app/db.py").read()
except OSError:
    db_src = ""
if "DB_PATH" not in db_src:
    sys.exit("ABORT: app/db.py has no DB_PATH symbol — the import would fail. "
             "No file written. (Check what the db module exposes.)")

try:
    ast.parse(text)
except SyntaxError as e:
    sys.exit(f"ABORT: result has a syntax error: {e}. No file written.")

with open(PATH, "w") as f:
    f.write(text)
print(f"OK: wrote {PATH} — restored upload_split wiring (import + STAGING_DIR + configure)")
