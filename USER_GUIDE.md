# Gaelic Shadowing Practice — User Guide

A guide to using the website at
`https://ceol-pi.tail01672f.ts.net:10000/`.

---

## What the site is for

This is a practice tool for Scottish Gaelic shadowing. Shadowing is a
language-learning technique where you listen to a short clip of a native
speaker and immediately repeat what you hear, mimicking their rhythm,
intonation, and pronunciation as closely as you can. Over time it helps
your ear, your mouth, and your accent catch up with each other.

The site holds two kinds of thing:

- **Individual clips** — a single short audio file with a description and a
  learner-advice note.
- **Collections** — a whole episode (e.g. an Litir Bheag) split into one
  clip per sentence, with the full transcript available, and a player
  that lets you loop sentences a chosen number of times or play a range
  of sentences back-to-back.

Anyone with the link can browse and listen. Only invited users can add new
clips, collections, or imports.

---

## How to access the site

Open this URL in any web browser, on any device:

```
https://ceol-pi.tail01672f.ts.net:10000/
```

You can bookmark it, share it, open it on a phone, a tablet, a laptop —
it works the same everywhere. The site is hosted on a small computer
(a Raspberry Pi) at home, exposed through a service called Tailscale
Funnel that lets it be reachable from the public internet.

### Why is the URL so long?

It's not a pretty domain. To get a pretty one (like
`gshadow.example.com`) you'd need to buy a domain name and configure DNS,
and that costs money and adds complexity. The Tailscale URL is free,
secure (proper HTTPS, locked padlock in the address bar), and works
straight away. If you ever want to switch to a custom domain later,
that's possible but not required.

---

## The home page

The home page is a menu. It shows three category cards:

- **An Litir Bheag** — shorter, simpler letters for learners.
- **Litir do Luchd-ionnsachaidh** — the full weekly letter for advanced learners.
- **Other audio** — anything else: podcasts, songs, recordings.

Each card shows how many collections are in that category. Click a card
to see all the collections within it; each collection on that page has
its own "Open →" button.

The top of every page has a breadcrumb trail (e.g. *Home › An Litir
Bheag › John Matheson of Shieldaig*) so you can climb back up at any
time.

---

## Listening to an individual clip

If you've uploaded a single one-off clip that isn't part of any
collection, it appears under "Loose individual clips" at the bottom of
the home page. Click play, listen, done.

---

## Listening to a collection (the shadowing workflow)

This is the part that's actually built for shadowing practice.

Click "Open →" on a collection card to go to its page. You'll see:

1. **A sticky player** at the top of the screen, with a Play button, a
   Stop button, and a "Repeat each clip" selector going from 1× to 5×.
2. **A list of clips below**, each with a checkbox, a number, and the
   sentence text (the Gaelic, where available).
3. **The full transcript** at the bottom of the page, hidden behind a
   "Gaelic transcript" expander you can click to reveal.
4. **An English translation** below that (if the source had one),
   similarly behind an expander.

### How to use the player

The player works on a "build a queue, then press play" model:

1. **Tick the checkboxes** next to the clips you want to play. By
   default every clip is ticked. Use **Select none** to start fresh, or
   **Select all** to put everything back.
2. **Choose how many times** to repeat each clip — 1× plays once, 5×
   plays each clip five times in a row before moving to the next.
3. **Press ▶ Play selected**. The player walks through your queue: it
   plays clip A `N` times, then clip B `N` times, then clip C, and so
   on. The currently-playing clip is highlighted in green.
4. **Press Stop** to halt immediately. Or press Play again to restart.

The status line on the right of the player tells you what's happening:
"Clip 03 — play 2/5 (queue 1/3)" means you're on your second of five
repetitions of clip 3, and clip 3 is the first of three clips in your
current queue.

### A suggested shadowing routine using the new player

For each collection:

1. **Listen passively first.** Untick everything, then tick the whole
   collection, set repeat to 1×, and let it play through end-to-end
   while you read along.
2. **Pick a sentence to work on.** Untick everything, then tick one
   single sentence. Set repeat to 5×. Press play. Speak along, trying
   to mimic the speaker's rhythm.
3. **Build up.** Once a sentence feels comfortable, tick the next one
   too (so your queue is two clips), and play. Keep adding.
4. **Test yourself.** Tick a range of five or six sentences, set repeat
   to 1×, and try to shadow without stopping.
5. **Come back tomorrow** and start at step 1 again. Repetition over
   days is what matters.

Five to ten minutes a day with this routine beats an hour once a week.

### Mobile use

The site is designed to work on phones. The player works the same:

- On iPhone, audio plays through the speaker or your AirPods. The
  system media controls show what's playing.
- On Android, same.
- Audio will pause if you switch apps. Tap the play button on the
  webpage to resume — the system controls don't always work to resume
  a queued session.

---

## For invited contributors only

The rest of this guide is for people who have been given a login. If
you're just here to listen, you can stop reading.

### Logging in

The login page is at:

```
https://ceol-pi.tail01672f.ts.net:10000/login
```

**Important:** the login page is restricted to the Tailscale network.
If you try to load it from a phone on cellular data or a computer that
isn't on the tailnet, you'll get a "403 Forbidden" error. This is
deliberate — it's how the site keeps random visitors out of the upload
form even though the browse page is public.

To get past this restriction, you need to be on the tailnet. That means
either:

- Using a device with the Tailscale app installed and logged in (your
  phone, laptop, etc.)
- Being on the home wifi network where the Pi lives, **if** that network
  is on the tailnet

If you've been invited as a contributor and don't have Tailscale set up,
ask the site owner — they'll need to invite your device to the tailnet
first.

Once you can load the login page, enter the email and password you were
given. After logging in successfully, you stay logged in for 14 days,
even across browser restarts. After that you need to log in again.

### Three ways to add content

Once logged in, the top right of the page shows three links:

- **Upload clip** — add a single audio clip with a description and
  advice (the old workflow; still useful for one-off recordings).
- **New collection** — bundle multiple files into a single collection
  in one go.
- **Import URL** — paste a learngaelic.scot URL and let the site
  download, split, and ingest it automatically.

Choose whichever fits what you have to hand.

---

### Upload clip — a single recording

Same as the original site. Title, description, advice, file. See the
"Recording tips" section at the end of this guide for what makes a good
clip.

---

### New collection — bulk upload from a folder of files

Use this when you already have a folder of numbered audio files (for
example, output from the Mac splitter script, or clips someone gave
you on a memory stick) and want to upload them as one set.

The form has six fields:

- **Title** — what the collection is called on the home page.
- **Category** — which section of the home page it appears under.
  Choose between *An Litir Bheag*, *Litir do Luchd-ionnsachaidh*, or
  *Other audio*. URL imports auto-fill this; bulk uploads default to
  *Other audio*.
- **Brief description** — one or two sentences about what it is.
  Speaker, source, date — whatever's useful.
- **Transcript (optional)** — paste the whole transcript here. It'll
  show up on the collection page behind an expander.
- **Notes / English translation (optional)** — a second expander block
  for translation, register notes, dialect, anything else.
- **Audio files** — pick **multiple** files at once. On macOS hold ⌘ to
  multi-select in the file picker. On Windows hold Ctrl.

**Important: filenames determine the order.** The clips appear in the
collection in alphabetical order by their original filename. So if you
upload `1.mp3, 2.mp3, 10.mp3`, they'll come out in the wrong order
(`1, 10, 2`). Use zero-padded filenames (`01.mp3, 02.mp3, …, 28.mp3`)
and the order will be right. The Mac splitter script does this for
you automatically.

After clicking **Create collection** you're taken straight to the new
collection's page. There's no preview screen — the upload happens in
one go.

---

### Import URL — paste a learngaelic.scot URL

This is the easiest way to add a whole episode. Currently the site
knows how to handle four learngaelic.scot URL patterns:

- `https://learngaelic.scot/litir/litir.jsp?l=N` (the full weekly Litir)
- `https://learngaelic.scot/litirbheag/litir.jsp?l=N` (the shorter Litir Bheag)
- `https://learngaelic.scot/look/look.jsp?b=ID` (Look@LearnGaelic — video interviews; audio extracted)
- `https://learngaelic.scot/watch/watch.jsp?v=N` (Watch Gaelic — video news/features; audio extracted)

For Litir and Litir Bheag, the audio is split into one clip **per
sentence**.

For Look and Watch (which are interview-style videos), the import
extracts the audio track from the video and splits it into one clip
**per speaker turn** — i.e. one clip is one continuous stretch of one
person talking, ending when another person starts. This matches the
natural rhythm of shadowing an interview better than sentence-level
splits would.

Paste the URL of an episode, press **Start import**, and you'll be
taken to a status page that auto-refreshes every few seconds. The
import does this:

1. **Fetches** the episode page from learngaelic.scot.
2. **Reads the transcript** and counts how many sentences it has.
3. **Downloads** the audio file (a `.caf` from CloudFront — usually
   2–5 MB).
4. **Decodes** it to WAV with ffmpeg.
5. **Detects sentence-boundary pauses** with ffmpeg's silence detector.
6. **Picks the right number of cut points** to match the sentence count.
7. **Splits the audio** into one MP3 per sentence.
8. **Creates a collection** with the full Gaelic transcript, the
   English transcript as a separate notes block, and each clip's
   description set to its Gaelic sentence.

Total time: about 30 seconds for a typical Litir Bheag, maybe a minute
for a full Litir.

If the import fails (network error, page structure changed, audio
unusually short) the status page will tell you why. Re-running on the
same URL is safe — it'll just create another collection with the same
content if you do.

Only one import can run at once. If you try to start a second while
the first is going, you'll get a clear "another import is running"
error. Wait a minute and try again.

#### Can I import other sites?

Right now: no. The import needs an adapter (a small piece of code that
knows the structure of a specific site). The two learngaelic.scot
sections are the only ones built in. For other audio you have two
choices:

- Use the **Mac splitter script** below to split locally on your Mac,
  then upload the resulting folder via **New collection**.
- Ask the site administrator to add an adapter for the new site (he needs to know the
  URL pattern, where the audio file lives on the page, and where the
  transcript lives on the page).

---

### Recording tips for good clips

If you're recording your own audio rather than importing existing
material:

- **Quiet background.** No traffic, no TV, no fan noise. A bedroom with
  the door closed beats a kitchen.
- **Normal speaking pace.** Don't slow down for the learner — that
  defeats the purpose. If a phrase is too fast to follow, learners can
  replay it.
- **Short clips.** 15 to 90 seconds is the sweet spot. For long
  recordings, split into one-sentence clips using the Mac splitter and
  upload as a collection — that's much more useful for shadowing than
  one long clip.
- **One topic per clip / collection.** Don't combine "greetings",
  "weather", and "ordering food" into one big file. Split them.
- **Just a phone is fine.** Voice Memos on iPhone or the built-in
  Recorder on Android both produce audio that's plenty good enough.
  No need for studio equipment.

---

## Deleting collections and clips

If you uploaded something by mistake — wrong audio, wrong title, or you
just want to clean up — you can delete it.

- **To delete a whole collection**: open the collection page, and you'll
  see a red **"Delete collection"** link just below the title. Clicking
  it asks you to confirm, then removes the collection, all its clips,
  and the audio files from the server.
- **To delete a single standalone clip** (one that isn't in a collection):
  open the home page, scroll down to "Loose individual clips", and each
  card has a **"Delete"** link at the bottom.

Both actions are **irreversible**. There's no undo or trash bin. Be
sure before you click.

Only admins and uploaders see these buttons; ordinary visitors don't.

---

## The Mac splitter script

For when you have audio that isn't on learngaelic.scot and you want it
split into sentence clips, there's a Python script that runs on your
Mac. It's in the project tarball as `mac-splitter.py`.

Prerequisites on your Mac:

- Python 3 (already installed on recent macOS).
- ffmpeg. Install with `brew install ffmpeg` if you have Homebrew, or
  download from <https://ffmpeg.org/>.

Basic use:

```
python3 mac-splitter.py my-podcast.mp3 --sentences 28
```

Tells the script to split into 28 clips. Output goes to a folder named
`my-podcast-clips/` next to the input file, containing `01.mp3`,
`02.mp3`, …, `28.mp3`.

Or pass a transcript and let the script count for you:

```
python3 mac-splitter.py my-podcast.mp3 --transcript transcript.txt
```

If the split is bad — clips too long, too short, or in the wrong
places — the script has two knobs you can tune:

```
python3 mac-splitter.py my-podcast.mp3 --sentences 28 \
  --noise-db -25 --min-pause 0.25
```

- `--noise-db` is the silence threshold in decibels. The default is
  `-30`. A **less negative** number (e.g. `-25`) means the script will
  count quieter sounds as "silence", giving you more cut candidates.
  Useful for very quiet recordings.
- `--min-pause` is the minimum pause duration (in seconds) for
  something to count as a sentence break. The default is `0.35` for
  sentence mode, `0.9` for speaker mode. A **smaller** number gives
  you more cut candidates. Useful for fast-paced speech.

### Splitting interviews by speaker turn instead of by sentence

If you've got an interview-style recording (alternating speakers, like
the Look@LearnGaelic videos) and you want each clip to be a whole
speaker turn rather than each individual sentence, add `--mode speakers`:

```
python3 mac-splitter.py interview.mp3 --sentences 12 --mode speakers
```

In speaker mode the script looks for longer pauses (the gap between
speakers tends to be ~1 second, vs ~0.4 seconds between sentences
within a single speaker's turn). One clip = one continuous stretch of
one person talking.

Use `--sentences N` to tell it how many turns you expect — count the
`[Speaker]` paragraphs in the transcript if there is one.

Once you have the folder of clips, upload it through **New
collection** on the website.

---

## Troubleshooting

### "The page won't load at all"

The Pi might be off or off the tailnet. Try again in a few minutes. If
it stays down, contact the site administrator.

### "I can browse but I can't log in — 403 Forbidden"

You're not on the tailnet. See the "Logging in" section above. Either
install Tailscale on your device, or connect from a device that already
has it.

### "The import is taking ages"

A full Litir (the longer series) can take up to a minute on the Pi.
Anything longer than two minutes probably means something is wrong —
check the status page for an error, and tell the site administrator if it's still
running with no progress message.

### "The import succeeded but the clips don't match the sentences"

ffmpeg's silence detector got confused — usually because the original
audio has unusual pacing or background noise. The import doesn't know
to retry with different settings. Workarounds:

- Download the audio yourself, run the Mac splitter with adjusted
  `--noise-db` or `--min-pause` settings, then upload via **New
  collection**.
- Or accept the collection as-is and use the transcript on the page to
  follow along — the sentences are right even if the clip cuts aren't.

### "Audio won't play"

Most likely an autoplay restriction on your browser. Tap or click the
play button explicitly. If it still won't play, try a different
browser — Safari, Chrome, and Firefox all work fine.

### "I uploaded clips into a collection in the wrong order"

The collection orders clips by their original filenames sorted as
strings. If your files were named `1.mp3, 2.mp3, …, 10.mp3` the
sorting will put `10` before `2`. You'll need to:

- Rename the files with zero-padding (`01.mp3`, `02.mp3`, …) on your
  Mac
- Delete the collection — there's a Delete button at the top of every
  collection page if you're logged in as an admin or uploader
- Re-upload with the corrected filenames

### "I forgot my password"

Contact the site administrator. There's no self-service password reset.

---

## A note on privacy

- Browsing is anonymous. The site doesn't track who's listening to
  what.
- Audio files (uploaded or imported) are stored on a Raspberry Pi in
  the administrator's location, not on a cloud service.
- The site is reachable on the public internet, so any audio you
  upload is publicly accessible to anyone with the URL. Don't upload
  anything you wouldn't want strangers to hear.
- For URL imports: the source URL is stored alongside the collection,
  so anyone browsing the site can see where each collection came from.
  This is a feature, not a bug — but worth knowing.

---

Happy shadowing. Mar sin leat!
