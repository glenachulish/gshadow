#!/usr/bin/env python3
"""Add two admin panels to the collection page, in ONE edit (this file holds
the resume + player JS, so we touch it exactly once):

  1. A "Series" dropdown + Save, after the title/delete block — assign this
     collection to a series (or clear it). Posts to /c/{slug}/series.
  2. An "Add existing clips" panel after the clips list — tick loose clips and
     add them to THIS collection. Posts to the existing /clips/assign with
     return_to set here. Forms are siblings (no nesting): the panel form wraps
     only the picker UI; each loose-clip checkbox associates via form=.

Requires view_collection to pass `series_list` and `loose_clips` (patch3a).
Run from ~/gshadow. Each anchor must match exactly once.
"""
import sys

PATH = "app/templates/collection.html"
text = open(PATH).read()

EDITS = [
    # 1. Series dropdown, inserted right after the delete-collection block.
    (
        "Insert series dropdown after the delete-collection form",
        '''    <form method="post" action="/c/{{ collection.slug }}/delete" class="inline-form"
          onsubmit="return confirm('Delete this whole collection and all its clips? This cannot be undone.');">
      <button type="submit" class="subtle" style="color: var(--error-fg);">Delete collection</button>
    </form>
  {% endif %}''',
        '''    <form method="post" action="/c/{{ collection.slug }}/delete" class="inline-form"
          onsubmit="return confirm('Delete this whole collection and all its clips? This cannot be undone.');">
      <button type="submit" class="subtle" style="color: var(--error-fg);">Delete collection</button>
    </form>
    <form method="post" action="/c/{{ collection.slug }}/series"
          style="display:flex; gap:0.5rem; align-items:center; flex-wrap:wrap; margin:0.5rem 0;">
      <label style="margin:0; color:var(--muted);">Series:</label>
      <select name="series_id" style="width:auto;">
        <option value="">— none (loose collection) —</option>
        {% for s in series_list %}
          <option value="{{ s.id }}" {% if series and s.id == collection.series_id %}selected{% endif %}>{{ s.title }}</option>
        {% endfor %}
      </select>
      <button type="submit" class="subtle">Save series</button>
      {% if not series_list %}
        <span style="color:var(--muted); font-size:0.85rem;">
          No series in this category yet — create one from the category page.
        </span>
      {% endif %}
    </form>
  {% endif %}''',
    ),
    # 2. "Add existing clips" panel, inserted after the clips-list closing </div>
    #    (which is followed by the transcript {% if %}). Anchor on that boundary.
    (
        "Insert add-existing-clips panel after the clips list",
        '''    {% endfor %}
  </div>

  {% if collection.transcript %}''',
        '''    {% endfor %}
  </div>

  {% if user and user.role in ['admin', 'uploader'] and loose_clips %}
    <details class="transcript" style="margin-top:1rem;">
      <summary>Add existing loose clips to this collection</summary>
      <div class="body">
        <form method="post" action="/clips/assign" id="add-existing-form">
          <input type="hidden" name="target_collection_id" value="{{ collection.id }}">
          <input type="hidden" name="return_to" value="/c/{{ collection.slug }}">
          <p style="color:var(--muted); font-size:0.9rem; margin:0 0 0.5rem;">
            Tick clips not yet in any collection to append them here, in order.
          </p>
          {% for lc in loose_clips %}
            <label style="display:flex; align-items:center; gap:0.5rem; padding:0.2rem 0;">
              <input type="checkbox" name="clip_ids" value="{{ lc.id }}">
              <span>{{ lc.title }}</span>
            </label>
          {% endfor %}
          <button type="submit" class="play" style="margin-top:0.5rem;">Add selected to this collection</button>
        </form>
      </div>
    </details>
  {% endif %}

  {% if collection.transcript %}''',
    ),
]

for desc, find, replace in EDITS:
    n = text.count(find)
    if n != 1:
        sys.exit(f"ABORT: edit '{desc}' matched {n} times (expected 1). No file written. "
                 f"Your collection.html is untouched.")
    text = text.replace(find, replace)

with open(PATH, "w") as f:
    f.write(text)
print(f"OK: wrote {PATH} — added series dropdown + add-existing-clips panel")
