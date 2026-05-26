# Session — 22 May 2026

## Summary

Three playback bugs fixed in `frontend/static/app.js`, delivered as a
single direct-replace patch script (`ceol_bugfix_22may.py`). JS-only —
no DB migration, no server restart needed beyond the normal Pi deploy.

| Bug | Area | Fix |
|-----|------|-----|
| 1 | Bar-range loop | Loop now ignores end-repeat barlines (`:|`) |
| 2 | Play buttons | Audio context no longer detached mid-playback |
| 3 | Set playback | Hidden→visible note map is now self-correcting |

Commit message:
`fix: loop ignores repeat barline; play-button silence; set highlight desync`

---

## Bug 1 — looping a bar that ends with `:|` replays the whole part

**Report:** Selecting bar 8 of Hogties to loop replayed the entire
A-part instead of just bar 8.

**Root cause.** Bar 8 is the last bar of the A-part and ends with a
`:|` end-repeat barline. `expandAbcRepeats()` does *not* unfold
repeats — so the synth obeys `:|` and replays bars 1–8 before ever
reaching bar 9. The loop-end logic computed "end of bar 8" as
"start of bar 9" (`_barFirstMs[end + 1]`). But `_barFirstMs` only
records each bar's *first* occurrence, so `_barFirstMs[8]` (bar 9) is
the time bar 9 first plays — i.e. *after* the repeated A-part. The
loop therefore ran from bar 8 to "after the second A-part pass",
which is bars 8 → 1–8 → back to 8.

**Fix.** In both `onEvent` loop blocks (modal `renderSheetMusic` and
fullscreen `openAbcFullscreen`), the loop end is now computed
repeat-aware:

- `_nextMs` = `_barFirstMs[end + 1]` (next bar's recorded time)
- `_linMs` = `_barMs(end) + _msPerMeasure` (clean one-bar estimate)
- If `_nextMs` is more than **half a bar** beyond `_linMs`, a repeat
  replayed a section in between — discard `_nextMs`, use `_linMs`.
- Otherwise behaviour is byte-identical to before (normal bars).

The half-bar threshold means ordinary bar-to-bar timing jitter never
triggers the override; only a genuine repeat (which adds several
bars of time) does. This is the literal "ignore the `:`" fix Callum
asked for, achieved by detecting the repeat's timing fingerprint
rather than parsing the ABC.

---

## Bug 2 — bottom play button: notes animate, no sound

**Report:** Play (top button) → pause → play (bottom button) gave
animation but silence. Top button worked again afterwards.

**Root cause.** `_ceolWakeAudio()` (cluster A patch 9) tries to
`resume()` the shared audio context, then 300 ms later, if it still
isn't `"running"`, **nulls `window.abcjsAudioContext`** so the next
`setTune()` can rebuild it. That design assumes a `setTune()` follows.
On the play-button path nothing calls `setTune()` — playback is
already underway. So 300 ms into playback the context gets detached
from the live synth: the cursor animation (a plain timer) keeps
going, but the sound is dead. The top button only "worked" because
by then the context was already null and abcjs lazily built a fresh
one.

**Fix.** In `_ceolWakeAudio()`'s 300 ms timeout, only null the
context if **no Play button is currently pushed**
(`.abcjs-midi-start.abcjs-pushed`). A synth that is mid-playback is
bound to the context and must keep it. A suspended/interrupted
context is left in place for `.resume()` to keep retrying — far
safer than guaranteeing silence by detaching it.

---

## Bug 3 — set playback: highlighting falls apart after the first tune

**Report:** Playing *Hogties Dub & Jock's 70th* as a set — note
animation worked for tune 1, then broke for the rest.

**Root cause.** Same class of bug as the 16 May "Ian, Frank and the
Razor" fix. The hidden→visible note map (`window._fsHiddenToVis`)
advances a cursor by `visibleNotes × repeats` per tune. The repeat
count comes from the `tuneRepeats` array threaded down into
`openAbcFullscreen`. If `tuneRepeats` is missing or stale for the
path used to open the set, `_reps` falls back to `1`, the cursor
advances too slowly, and every tune after the first maps to the
wrong visible notes — so later tunes stop lighting up.

**Fix.** The map builder is now **self-correcting**. It computes the
implied total note count from `Σ(visibleNotes_i × reps_i)` and
compares it to the real hidden note count. On a mismatch it recovers
a uniform repeat multiplier directly from
`hiddenNotes.length / Σ visibleNotes` and rebuilds the per-tune
blocks with that. Block boundaries therefore always land on an exact
multiple of each tune's visible-note count, whether or not
`tuneRepeats` arrives intact. This also correctly handles the case
where the hidden render is *folded* (no unfolded repeats) — the
recovered multiplier is simply 1.

**Note for future work.** The remaining unhandled edge case is a set
with genuinely non-uniform per-tune repeat counts *and* a missing
`tuneRepeats` array. That is rare (the app defaults every tune to 2
repeats; differing counts require manual per-tune editing). If it
ever surfaces, the proper fix is to thread `tuneRepeats` reliably
from *every* set-open entry point, or to segment the hidden render by
`tuneRanges` start/end chars instead of by counts.

---

## Files changed

- `frontend/static/app.js` — 4 code edits (Bug 1 is two: modal +
  fullscreen loop blocks)
- `frontend/mobile.html` — `app.js?v=` cache-bust bumped

The patch script (`ceol_bugfix_22may.py`) verifies all four target
blocks match exactly once before writing anything, and backs up
`app.js` to `app.js.bak-<timestamp>` first — so it cannot half-apply.

## Deploy

1. `python3 ~/Downloads/ceol_bugfix_22may.py` (local Mac)
2. `git add frontend/static/app.js frontend/mobile.html` → commit → push
3. Pi: `git pull` + `sudo systemctl restart ceol`
4. iPhone: fully close and reopen the PWA so new `app.js` loads.

## Test checklist

- [ ] Hogties: select bar 8 to loop → loops bar 8 only, not bars 1–8.
- [ ] A loop on a non-repeat bar still loops correctly (no regression).
- [ ] Play (top) → pause → play (bottom) → sound *and* animation.
- [ ] Same with buttons swapped.
- [ ] Play *Hogties Dub & Jock's 70th* as a set → highlight tracks
      every tune, including the second and any later ones, through
      all repeats.
