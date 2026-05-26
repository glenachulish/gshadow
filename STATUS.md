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

---

## Feature work — current status

### 1. Audiobook splitting (`mac-splitter.py`)

- **DONE:** new `--mode pauses` written and committed. It is
  threshold-driven (splits at every pause over a threshold, no target
  count needed), tuned for breath-group clips ~5–15s, with
  `--min-clip-len` and `--max-clip-len` safety knobs. Existing
  `sentences` / `speakers` modes left untouched.
- **NOT DONE / OPEN:** has not been verified to actually split. In the
  one trial, clips uploaded but no splitting appeared to happen — needs
  investigation. Possible causes to check: was `--mode pauses` actually
  passed; did the new file land in `~/gshadow`; did ffmpeg run. Do NOT
  consider this feature complete until a real audiobook chapter has been
  split and the per-clip duration table looks right.
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
- [ ] Connect the `gshadow` GitHub repo to this Claude Project
- [ ] Refile `~/Desktop/misfiled-from-gshadow/` contents into the Òrain
      and Ceòl projects
- [ ] Decide whether `~/dot-git-OLD-home-repo` can be deleted (low priority)

### Audiobook splitting
- [ ] **Investigate why no splitting occurred** in the first trial
- [ ] Test `--mode pauses` on a real audiobook chapter; confirm clip
      durations land ~5–15s
- [ ] Tune defaults (`--min-pause`, `--min-clip-len`, `--max-clip-len`)
      if needed
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

### New ideas raised (not yet scheduled)
- [ ] **Move clips between "loose individual clips" and a collection from
      within the website** — currently the only way to get clips into a
      collection is to re-upload them from the computer, which is not
      intuitive. Add an in-page way to assign existing loose clips to a
      collection (and possibly move them back out).

---

## Open questions / decisions pending

- Whisper: worth the effort, or skip? (Affects feature 2.)
- Does Litir Bheag carry a vocabulary block? (Affects feature 3.)
- Should the in-page clip-moving feature also allow reordering within a
  collection? (Related: repo notes already list "no drag-to-reorder" as
  a deliberate omission.)
