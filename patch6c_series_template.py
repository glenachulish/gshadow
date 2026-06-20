#!/usr/bin/env python3
"""Add chapter-ordering controls to the series page (admin/uploader only):
a number box per chapter (pre-filled with its current position) and a
"Save order" button. Posts pos_<id>=<number> to /series/{slug}/order.

For non-admins the page is unchanged. The order <form> wraps the chapter list
only when admin; each number box sits inside its card. No JS.

Run from ~/gshadow. Each anchor must match exactly once.
"""
import sys

PATH = "app/templates/series.html"
text = open(PATH).read()

EDITS = [
    # 1. Open the order form (admin only) right before the chapter loop, and
    #    add a hint. Anchor on the "no chapters" block + the loop start.
    (
        "Open order form before the chapter loop",
        '''  {% if not collections %}
    <p style="color: var(--muted);">No chapters in this series yet. Add one from the
      <a href="/collections/new">New collection</a> form and choose this series.</p>
  {% endif %}

  {% for c in collections %}
    <div class="collection-card">
      <div class="body">
        <h3>{{ c.title }}</h3>
        {% if c.description %}<p class="meta">{{ c.description }}</p>{% endif %}
        <p class="meta">{{ c.clip_count }} clip{{ '' if c.clip_count == 1 else 's' }}</p>
      </div>
      <a class="open" href="/c/{{ c.slug }}">Open →</a>
    </div>
  {% endfor %}''',
        '''  {% if not collections %}
    <p style="color: var(--muted);">No chapters in this series yet. Add one from the
      <a href="/collections/new">New collection</a> form and choose this series.</p>
  {% endif %}

  {% if user and user.role in ['admin', 'uploader'] and collections %}
    <form method="post" action="/series/{{ series.slug }}/order">
      <p style="color: var(--muted); font-size: 0.9rem; margin: 0 0 0.5rem;">
        Set the order: type a number in each chapter, then Save. The numbers
        just express order — they'll be tidied to 1, 2, 3… on save.
      </p>
      {% for c in collections %}
        <div class="collection-card">
          <div class="body" style="display:flex; align-items:center; gap:0.75rem;">
            <input type="number" name="pos_{{ c.id }}" value="{{ c.series_position if c.series_position is not none else '' }}"
                   min="1" step="1" style="width:4rem;" aria-label="Order for {{ c.title }}">
            <div>
              <h3 style="margin:0;">{{ c.title }}</h3>
              {% if c.description %}<p class="meta" style="margin:0;">{{ c.description }}</p>{% endif %}
              <p class="meta" style="margin:0;">{{ c.clip_count }} clip{{ '' if c.clip_count == 1 else 's' }}</p>
            </div>
          </div>
          <a class="open" href="/c/{{ c.slug }}">Open →</a>
        </div>
      {% endfor %}
      <button type="submit" class="subtle" style="margin-top:0.5rem;">Save order</button>
    </form>
  {% else %}
    {% for c in collections %}
      <div class="collection-card">
        <div class="body">
          <h3>{{ c.title }}</h3>
          {% if c.description %}<p class="meta">{{ c.description }}</p>{% endif %}
          <p class="meta">{{ c.clip_count }} clip{{ '' if c.clip_count == 1 else 's' }}</p>
        </div>
        <a class="open" href="/c/{{ c.slug }}">Open →</a>
      </div>
    {% endfor %}
  {% endif %}''',
    ),
]

for desc, find, replace in EDITS:
    n = text.count(find)
    if n != 1:
        sys.exit(f"ABORT: edit '{desc}' matched {n} times (expected 1). No file written. "
                 f"Your series.html is untouched.")
    text = text.replace(find, replace)
with open(PATH, "w") as f:
    f.write(text)
print(f"OK: wrote {PATH} — added per-chapter order boxes + Save (admin only)")
