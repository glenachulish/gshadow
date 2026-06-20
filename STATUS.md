# Gàidhlig Shadowing Site — Project Notes & Status

*Created 2026-05-26. This is the canonical maintainer status doc. Future
sessions should build on THIS file: update the status, tick off completed
to-do items, add new ones. Keep one living copy in `~/gshadow`, committed
to GitHub.*

---

## What this project is

A self-hosted website for Scottish Gaelic shadowing practice. FastAPI +
SQLite + Jinja2, running on a Raspberry Pi (`ceol-pi`), exposed via
Tailscale Funnel at `https://ceol-pi.tail01672f.ts.net:10000/`. Visitors
browse audio clips and collections; invited contributors upload content.
Full architecture is described in the repo's existing `PROJECT_NOTES.md`
and `USER_GUIDE.md` — this file is the live STATUS layer on top of that.

This project is also known internally as **gshadow**. It is NOT the same
as "Òrain" (a separate song-lyrics app) or "Ceòl" (a separate tunes app),
despite earlier folder-naming confusion — see history below.

---

## Where the code lives (the setup, as of 2026-05-26)

- **Canonical running copy:** the Raspberry Pi, `/home/pi/gshadow/`.
- **GitHub:** `https://github.com/glenachulish/gshadow` (private).
- **Working copy on the Mac:** `~/gshadow/`.
- **Deploy path:** edit on the Mac → commit/push to GitHub → `rsync` to
  the Pi → restart the `gshadow` service. (rsync + restart one-liners are
  in the repo's `PROJECT_NOTES.md` under "Operations".)
- The Mac's `.env` holds the real `GSHADOW_SECRET` and is gitignored —
  it must never be committed.

### How we work with Claude going forward

Claude (in the web chat) has NO direct access to the Pi, the Mac, or
GitHub. Each chat session starts with an empty workspace. Therefore:

- Code/notes Claude writes are created in a temporary sandbox and handed
  back as downloads. They are not "saved" anywhere until Callum places
  them in `~/gshadow` and commits/pushes them.
- **TODO (infrastructure):** connect the `gshadow` GitHub repo to this
  Claude Project, so future sessions can read the current committed code
  directly without re-uploading. Until then, code must be pasted/uploaded
  into each session.
- This notes file should be updated and re-committed at the end of each
  working session.

---

## Session history

### 2026-05-26 — Infrastructure disentangling (major)

The bulk of this session was untangling a confused setup, not feature
work. What happened:

- Discovered the live code existed only on the Pi; the Mac folder held a
  stale early version; the old GitHub repo held only 3 fossil files.
- Pulled the real 38-file project down from the Pi to the Mac via rsync.
- Found three separate projects had become tangled in one folder named
  `Orain`: the shadowing site (this project), the "Òrain" song-lyrics
  app, and stray Ceòl files.
- Disarmed a dangerous git repo that was rooted at the Mac home folder
  (would have risked pushing SSH keys etc. to a public repo). Its old
  `.git` is parked at `~/dot-git-OLD-home-repo` — safe to delete once
  fully confident, but no rush.
- Created a proper git repo inside `~/gshadow`, pushed the real code.
- Renamed the GitHub repo `Orain` → `gshadow`, made it private, fixed
  its description.
- Renamed the Mac folder `~/Orain` → `~/gshadow`.
- Moved misfiled files (the `backend/` song-app folder, `setup_orain.sh`,
  song-app and Ceòl notes) out to `~/Desktop/misfiled-from-gshadow/` for
  refiling into their own projects.
- Wrote audiobook pause-splitting into `mac-splitter.py` and committed
  it. **Not yet tested — see open issues.**

### 2026-06-18 — Audiobook splitting verified; repo connected

- Connected the `gshadow` GitHub repo to the Claude Project (repo made
  public to do so; can go back to private now).
- Tracked down the "no splitting" problem: **ffmpeg was not installed on
  the Mac.** Installed ffmpeg 8.1.2 via Homebrew.
- Verified `--mode pauses` end to end on `cabideil 1.mp3` (85.5s → 14
  clips, 3.9–9.8s, cuts good by ear). Audiobook feature now considered
  working. Marked the open issue RESOLVED.
- Confirmed there is **no PWA** for the site (asked and checked — not
  built, not on the roadmap).
- Note: nothing required a Pi deploy this session — the splitter is a
  Mac-side tool and clips reach the Pi via the web upload form. The only
  change is this STATUS.md update (docs commit, no rsync/restart).

### 2026-06-20 — Resume, in-app splitting, per-clip delete (feature session)

A long, multi-deploy session. Several features shipped to the Pi and
verified in real use:

- **Per-device resume position** — built and deployed. First version had
  an off-by-one (Resume re-selected the clip just finished, so finishing
  clip 1 selected the whole collection); fixed to resume at clip N+1 with
  an end-of-collection "Start over" case. Verified working. One file
  (`app/templates/collection.html`).
- **In-app split-on-upload with preview/accept** — the big one. New
  `/split` page: upload one long file, it splits at pauses on the Pi,
  shows a preview with per-clip players + durations, then Accept (create
  collection) / Re-run at a different sensitivity / Cancel. New files:
  `app/splitter.py` (shared cut logic, also usable by the CLI),
  `app/upload_split.py` (job worker + accept/cancel), `split.html`,
  `split_job.html`. Edits to `db.py` (new `split_jobs` table),
  `collections.py` (the routes), `main.py` (wiring). Reuses the existing
  import lock so a split and a URL import can't run at once.
- **Deployment gotcha found and fixed:** the systemd service runs with
  `ProtectSystem=strict` and `ReadWritePaths=.../data .../audio`, so the
  app can only write to `data/` and `audio/`. Staging was first put at
  `~/gshadow/staging` (read-only under the sandbox → 500 error on upload);
  moved to `data/staging`, which is writable. Recorded for future
  features that need to write files.
- **Per-clip delete on collection pages** — the delete route already
  existed; added a per-row Delete button (admin/uploader only) to
  `collection.html`. Verified working.
- **Nav link** — added "Split a long file" to the top nav in `base.html`
  (the feature was unreachable except by typing the URL until this).
- Process note: a couple of false-start failures this session were the
  shell being in `~` instead of `~/gshadow`, and a transient port clash
  during a manual uvicorn test colliding with the systemd restart — not
  code bugs. The Mac's own `.venv` can't import the app (no jinja2, and a
  stray `orain` venv intercepts pip), so app-import sanity checks must be
  run on the Pi, not the Mac.

---

## Feature work — current status

### 1. Audiobook splitting (`mac-splitter.py`)

- **DONE:** new `--mode pauses` written and committed. It is
  threshold-driven (splits at every pause over a threshold, no target
  count needed), tuned for breath-group clips ~5–15s, with
  `--min-clip-len` and `--max-clip-len` safety knobs. Existing
  `sentences` / `speakers` modes left untouched.
- **RESOLVED 2026-06-18:** `--mode pauses` works correctly. The earlier
  "no splitting" trial was caused by **ffmpeg not being installed on the
  Mac** — `check_tools()` exited before any work happened, so nothing was
  ever cut. (The clips uploaded in that trial must have come from an
  earlier run or another source.) With ffmpeg 8.1.2 installed via
  Homebrew, a real chapter (`cabideil 1.mp3`, 85.5s) produced 14 clips of
  3.9–9.8s, all within the breath-group target. Cuts verified by ear as
  landing in sensible places.
- **Decision recorded:** audiobooks are split one folder per CHAPTER
  (Callum splits chapters first), each chapter → one collection. A whole
  book as one collection would be thousands of clips on one page.

### 2. Whisper for Gaelic transcripts

- **NOT STARTED (discussion only).** Findings so far: stock OpenAI
  Whisper does not handle Scottish Gaelic well. The Edinburgh "ÈIST"
  project released a Gaelic-fine-tuned Whisper model in 2025 that does.
  Recommendation: run it on the Mac (not the Pi — too slow / low RAM),
  as an optional transcribe step in the splitter; treat output as a
  DRAFT for human correction, never publish raw. Not yet designed or
  built.

### 3. Three transcript blocks on collections

- **NOT STARTED (designed only).** Goal: every collection (all
  categories) shows three clickable expanders below the audio —
  Gàidhlig, Beurla, and language notes. Currently the schema has only
  `transcript` (Gaelic) + `notes` (English); the Litir adapter discards
  the vocabulary/grammar apparatus. Plan: add a `language_notes` column
  (idempotent migration), keep the Litir vocab block instead of
  discarding it, add a form field for bulk uploads, render three
  expanders in the collection template. Roughly five files affected;
  needs the Pi deploy.

### 4. In-app split-on-upload (DONE 2026-06-20)

- **DONE and verified.** `/split` page (linked in nav). Upload one long
  file → splits at pauses on the Pi → preview with per-clip players →
  Accept / Re-run (gentle/normal/fine/finest) / Cancel. Cut logic shared
  with the CLI via `app/splitter.py`. Job state in a new `split_jobs`
  table. Staging lives in `data/staging/` (must be under `data/` or
  `audio/` — the only writable paths under the systemd sandbox). 25 MB
  upload cap kept, so it remains a per-chapter tool.
- Open: hasn't been tuned across many files yet; timing on a full chapter
  on the Pi not yet recorded — watch for slow splits / page timeouts.

### 5. Per-device resume position (DONE 2026-06-20)

- **DONE and verified.** `localStorage` per collection slug; resumes at
  the next unfinished clip. Pure frontend, in `collection.html`.

### 6. Per-clip delete on collection pages (DONE 2026-06-20)

- **DONE and verified.** Per-row Delete button (admin/uploader), using
  the pre-existing `/clips/{id}/delete` route.

---

## To-do list

*Tick items when done. Add new items as they arise. Keep newest/active
items grouped sensibly.*

### Infrastructure
- [x] Get real code off the Pi and onto the Mac
- [x] Create a proper git repo for the shadowing site
- [x] Push current code to GitHub
- [x] Rename repo + Mac folder to `gshadow`; make repo private
- [x] Remove misfiled Òrain / Ceòl files from the folder
- [x] Connect the `gshadow` GitHub repo to this Claude Project
      (done 2026-06-18; repo made public temporarily to connect, can be
      set back to private)
- [ ] Refile `~/Desktop/misfiled-from-gshadow/` contents into the Òrain
      and Ceòl projects
- [ ] Decide whether `~/dot-git-OLD-home-repo` can be deleted (low priority)

### Audiobook splitting
- [x] **Investigate why no splitting occurred** in the first trial
      (cause: ffmpeg was not installed on the Mac)
- [x] Test `--mode pauses` on a real audiobook chapter; confirm clip
      durations land ~5–15s (cabideil 1: 14 clips, 3.9–9.8s ✓)
- [ ] Tune defaults (`--min-pause`, `--min-clip-len`, `--max-clip-len`)
      if needed — only one file tested so far; defaults looked good
- [ ] Update `USER_GUIDE.md` with audiobook / `--mode pauses` instructions
- [ ] (Optional, later) provide a one-line ffmpeg command to split an
      `.m4b` into per-chapter files using its chapter markers

### Transcripts (feature 3)
- [ ] Add `language_notes` column to `collections` (idempotent migration)
- [ ] Stop the Litir adapter discarding the vocab/grammar block; route it
      into `language_notes`
- [ ] Verify whether Litir Bheag pages even carry a vocab block
- [ ] Add a "Language notes" field to the New Collection form
- [ ] Render three expanders (Gàidhlig / Beurla / Notaichean cànain)
      under the player on the collection page, each shown only if present

### Whisper (feature 2)
- [ ] Decide whether to pursue ÈIST Gaelic Whisper at all
- [ ] If yes: add an optional `--transcribe` step to `mac-splitter.py`
- [ ] Treat all ASR output as draft-for-correction, never auto-publish

### Done 2026-06-20
- [x] In-app split-on-upload with preview/accept/re-run (`/split`)
- [x] Per-clip delete on collection pages
- [x] "Split a long file" nav link

### New ideas raised (not yet scheduled)
- [ ] **Move clips between "loose individual clips" and a collection from
      within the website** — currently the only way to get clips into a
      collection is to re-upload them from the computer, which is not
      intuitive. Add an in-page way to assign existing loose clips to a
      collection (and possibly move them back out).
- [ ] **Group collections under an overarching parent ("book"/"series").**
      e.g. two chapters of an audiobook, each its own collection, sitting
      under one parent. NOT a small change — likely a new table or a
      nullable `parent_id` on `collections`, a migration, and changes to
      home/category browsing, breadcrumbs, and several templates. Needs a
      design pass first (separate grouping vs. extending categories; what
      happens to ungrouped collections; one parent or many). Own session.
      Handover prompt already written 2026-06-20.

---

## Open questions / decisions pending

- Whisper: worth the effort, or skip? (Affects feature 2.)
- Does Litir Bheag carry a vocabulary block? (Affects feature 3.)
- Should the in-page clip-moving feature also allow reordering within a
  collection? (Related: repo notes already list "no drag-to-reorder" as
  a deliberate omission.)
- Collection grouping: should a "book"/"series" be a separate grouping
  that cuts across categories, or an extension of the category system?
  Should a collection belong to one parent or several? (Affects the
  next-session grouping feature.)

## Added 2026-05-26 (later)

- [ ] **"Currently working on" filter on collections.** Add an
      `in_progress` boolean column to `collections` (idempotent
      migration); toggle button on the collection page (admin/uploader);
      filter chip on category/home pages; a `/working-on` index. Per
      collection, not per user — this is a personal site with a curated
      "what I'm working on" shelf. ~5 files; Pi deploy.
- [x] **Resume position within a collection.** DONE & verified
      2026-06-20. Per-device `localStorage` per slug; resumes at the next
      unfinished clip; "Start over" at end of collection. One file
      (`collection.html`).
