#!/usr/bin/env python3
"""Let split-accept target an EXISTING collection (append) as well as create a
new one. Modifies upload_split.accept_job:

  accept_job(conn, job_id, uploaded_by, target_collection_id=None)

  - target_collection_id is None  -> behave exactly as now: create a new
    collection from job.title/category, insert clips at positions 1..N.
  - target_collection_id is set   -> append the staged clips to that existing
    collection, continuing its position numbering after the current max.
    No new collection row; the collection's title/category are untouched.

The audio-file move + per-clip INSERT + rollback-on-failure logic is shared by
both paths. Returns the destination collection's slug either way.

Run from ~/gshadow. Anchors must match exactly once; result must parse.
"""
import ast
import sys

PATH = "app/upload_split.py"
text = open(PATH).read()

# Replace the whole accept_job body from its def line through the final
# `return slug`. Anchor on the verbatim current function.
OLD = '''def accept_job(conn: sqlite3.Connection, job_id: int, uploaded_by: int):
    """Promote staged clips into a real collection. Returns the new slug.

    Raises ValueError if the job isn't in a ready state or staging is gone.
    """
    job = conn.execute(
        "SELECT id, title, category, status FROM split_jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    if not job:
        raise ValueError("Job not found.")
    if job["status"] != "ready":
        raise ValueError("This split isn't ready to accept.")
    meta = read_meta(job_id)
    if not meta or not meta.get("clips"):
        raise ValueError("No proposed clips found to accept.")

    clips_dir = _job_dir(job_id) / "clips"

    # Slug uniqueness (same approach as collections._make_slug_unique).
    from . import collections as cols
    slug = cols._make_slug_unique(conn, cols._slugify(job["title"]))

    cur = conn.execute(
        "INSERT INTO collections (slug, title, description, transcript, notes, "
        "source_url, category, uploaded_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (slug, job["title"], "", "", "", None, job["category"],
         uploaded_by, _now()),
    )
    collection_id = cur.lastrowid

    moved: List[Path] = []
    try:
        for clip in meta["clips"]:
            src = clips_dir / clip["filename"]
            dest_name = f"{uuid.uuid4().hex}.mp3"
            dest = _audio_dir / dest_name
            dest.write_bytes(src.read_bytes())
            moved.append(dest)
            conn.execute(
                "INSERT INTO clips (title, description, advice, filename, "
                "uploaded_by, uploaded_at, collection_id, position) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"Clip {clip['position']:02d}", "", None, dest_name,
                 uploaded_by, _now(), collection_id, clip["position"]),
            )
        conn.commit()
    except Exception:
        for p in moved:
            p.unlink(missing_ok=True)
        conn.execute("DELETE FROM clips WHERE collection_id = ?", (collection_id,))
        conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
        conn.commit()
        raise

    _update_job(conn, job_id, status="accepted", collection_id=collection_id,
                message=f"Accepted into collection '{job['title']}'.")
    cleanup_staging(job_id)
    return slug'''

NEW = '''def accept_job(conn: sqlite3.Connection, job_id: int, uploaded_by: int,
               target_collection_id: Optional[int] = None):
    """Promote staged clips into a collection. Returns the collection slug.

    If target_collection_id is None, a NEW collection is created from the job's
    title/category. If it is set, the staged clips are APPENDED to that existing
    collection, continuing its position numbering. Either way the audio files
    are moved into the audio dir and clip rows inserted; on any failure the
    newly added rows/files are rolled back.

    Raises ValueError if the job isn't ready, staging is gone, or a given
    target collection doesn't exist.
    """
    job = conn.execute(
        "SELECT id, title, category, status FROM split_jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    if not job:
        raise ValueError("Job not found.")
    if job["status"] != "ready":
        raise ValueError("This split isn't ready to accept.")
    meta = read_meta(job_id)
    if not meta or not meta.get("clips"):
        raise ValueError("No proposed clips found to accept.")

    clips_dir = _job_dir(job_id) / "clips"

    from . import collections as cols

    created_new = target_collection_id is None
    if created_new:
        # Create a fresh collection (original behaviour).
        slug = cols._make_slug_unique(conn, cols._slugify(job["title"]))
        cur = conn.execute(
            "INSERT INTO collections (slug, title, description, transcript, notes, "
            "source_url, category, uploaded_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (slug, job["title"], "", "", "", None, job["category"],
             uploaded_by, _now()),
        )
        collection_id = cur.lastrowid
        start_pos = 1
    else:
        # Append to an existing collection.
        target = conn.execute(
            "SELECT id, slug FROM collections WHERE id = ?",
            (target_collection_id,),
        ).fetchone()
        if not target:
            raise ValueError("Target collection not found.")
        collection_id = target["id"]
        slug = target["slug"]
        row = conn.execute(
            "SELECT COALESCE(MAX(position), 0) AS maxpos FROM clips "
            "WHERE collection_id = ?", (collection_id,),
        ).fetchone()
        start_pos = (row["maxpos"] or 0) + 1

    moved: List[Path] = []
    inserted_clip_ids: List[int] = []
    try:
        for offset, clip in enumerate(meta["clips"]):
            pos = start_pos + offset
            src = clips_dir / clip["filename"]
            dest_name = f"{uuid.uuid4().hex}.mp3"
            dest = _audio_dir / dest_name
            dest.write_bytes(src.read_bytes())
            moved.append(dest)
            cur = conn.execute(
                "INSERT INTO clips (title, description, advice, filename, "
                "uploaded_by, uploaded_at, collection_id, position) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"Clip {pos:02d}", "", None, dest_name,
                 uploaded_by, _now(), collection_id, pos),
            )
            inserted_clip_ids.append(cur.lastrowid)
        conn.commit()
    except Exception:
        for p in moved:
            p.unlink(missing_ok=True)
        # Roll back only the rows WE added — never touch pre-existing clips.
        for cid in inserted_clip_ids:
            conn.execute("DELETE FROM clips WHERE id = ?", (cid,))
        if created_new:
            conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
        conn.commit()
        raise

    _update_job(conn, job_id, status="accepted", collection_id=collection_id,
                message=f"Accepted into collection '{slug}'.")
    cleanup_staging(job_id)
    return slug'''

if text.count(OLD) != 1:
    sys.exit(f"ABORT: accept_job anchor matched {text.count(OLD)} times (expected 1). "
             f"No file written.")
text = text.replace(OLD, NEW)
try:
    ast.parse(text)
except SyntaxError as e:
    sys.exit(f"ABORT: result has a syntax error: {e}. No file written.")
with open(PATH, "w") as f:
    f.write(text)
print(f"OK: wrote {PATH} — accept_job now supports target_collection_id (append)")
