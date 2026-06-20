#!/usr/bin/env python3
"""Add an 'assign loose clips to a collection' picker to the home page.

Design note: HTML forms cannot nest. Each clip already has its own delete
<form>. So the assign <form> is rendered as JUST the bar (select + submit) and
sits OUTSIDE the clip loop; each clip's checkbox associates with it via the
HTML `form="assign-form"` attribute, which works regardless of DOM position.
That keeps the delete forms valid and avoids nesting.

Admin/uploader only. Run from ~/gshadow. Validates the single anchor matched
once before writing. The index route must also pass `collections` to the
template — patch2b (main.py) handles that.
"""
import sys

PATH = "app/templates/index.html"
text = open(PATH).read()

OLD = '''  {% if clips %}
    <h2 style="margin-top: 2rem;">Loose individual clips</h2>
    <p style="color: var(--muted); font-size: 0.9rem;">
      Single clips not yet in any collection.
    </p>
    {% for clip in clips %}
      <div class="clip">
        <h3>{{ clip.title }}</h3>
        {% if clip.description %}<p class="desc">{{ clip.description }}</p>{% endif %}
        <audio controls preload="none" src="/audio/{{ clip.filename }}"></audio>
        {% if clip.advice %}<div class="advice">{{ clip.advice }}</div>{% endif %}
        {% if user and user.role in ['admin', 'uploader'] %}
          <form method="post" action="/clips/{{ clip.id }}/delete" class="inline-form"
                onsubmit="return confirm('Delete this clip? This cannot be undone.');">
            <button type="submit" class="subtle" style="color: var(--error-fg);">Delete</button>
          </form>
        {% endif %}
      </div>
    {% endfor %}
  {% endif %}'''

NEW = '''  {% if clips %}
    <h2 style="margin-top: 2rem;">Loose individual clips</h2>
    <p style="color: var(--muted); font-size: 0.9rem;">
      Single clips not yet in any collection.
    </p>

    {% if user and user.role in ['admin', 'uploader'] and collections %}
      <form method="post" action="/clips/assign" id="assign-form">
        <input type="hidden" name="return_to" value="/">
        <div class="assign-bar" style="display:flex; gap:0.5rem; align-items:center;
             flex-wrap:wrap; background:#eef5ef; border:1px solid var(--border);
             border-radius:8px; padding:0.6rem 0.9rem; margin-bottom:1rem;">
          <span style="color:var(--muted);">Tick clips below, then add them to:</span>
          <select name="target_collection_id" required style="width:auto;">
            <option value="" selected disabled>Choose a collection…</option>
            {% for col in collections %}
              <option value="{{ col.id }}">{{ col.title }}</option>
            {% endfor %}
          </select>
          <button type="submit" class="play" style="margin:0;">Add selected</button>
        </div>
      </form>
    {% endif %}

    {% for clip in clips %}
      <div class="clip">
        {% if user and user.role in ['admin', 'uploader'] and collections %}
          <label style="display:inline-flex; align-items:center; gap:0.4rem; margin-bottom:0.3rem;">
            <input type="checkbox" name="clip_ids" value="{{ clip.id }}" form="assign-form">
            <span style="color:var(--muted); font-size:0.85rem;">select</span>
          </label>
        {% endif %}
        <h3>{{ clip.title }}</h3>
        {% if clip.description %}<p class="desc">{{ clip.description }}</p>{% endif %}
        <audio controls preload="none" src="/audio/{{ clip.filename }}"></audio>
        {% if clip.advice %}<div class="advice">{{ clip.advice }}</div>{% endif %}
        {% if user and user.role in ['admin', 'uploader'] %}
          <form method="post" action="/clips/{{ clip.id }}/delete" class="inline-form"
                onsubmit="return confirm('Delete this clip? This cannot be undone.');">
            <button type="submit" class="subtle" style="color: var(--error-fg);">Delete</button>
          </form>
        {% endif %}
      </div>
    {% endfor %}
  {% endif %}'''

n = text.count(OLD)
if n != 1:
    sys.exit(f"ABORT: anchor matched {n} times (expected 1). No file written. "
             f"Your index.html is untouched.")
text = text.replace(OLD, NEW)
with open(PATH, "w") as f:
    f.write(text)
print(f"OK: wrote {PATH} — added assign picker (bar-only form) + per-clip checkboxes")
