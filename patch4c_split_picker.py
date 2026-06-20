#!/usr/bin/env python3
"""Add a 'create new vs add to existing collection' picker to the split preview
accept form. The accept <form> gains a dropdown: default "Create a new
collection" (value blank) plus every existing collection. Posts the choice as
target_collection_id, which patch4b's route forwards to accept_job.

Run from ~/gshadow. Anchor must match exactly once.
"""
import sys

PATH = "app/templates/split_job.html"
text = open(PATH).read()

OLD = '''      <form method="post" action="/split/{{ job.id }}/accept" class="inline-form"
            onsubmit="return confirm('Create the collection from these {{ clips|length }} clips?');">
        <button type="submit">Accept — create collection</button>
      </form>'''

NEW = '''      <form method="post" action="/split/{{ job.id }}/accept"
            style="display:flex; gap:0.5rem; align-items:center; flex-wrap:wrap;"
            onsubmit="return confirm('Add these {{ clips|length }} clips to the chosen collection?');">
        <label style="margin:0; font-weight:normal;">Add to
          <select name="target_collection_id" style="width:auto; display:inline-block;">
            <option value="" selected>a new collection ({{ job.title }})</option>
            {% for col in all_collections %}
              <option value="{{ col.id }}">{{ col.title }}</option>
            {% endfor %}
          </select>
        </label>
        <button type="submit">Accept</button>
      </form>'''

if text.count(OLD) != 1:
    sys.exit(f"ABORT: anchor matched {text.count(OLD)} times (expected 1). "
             f"No file written. Your split_job.html is untouched.")
text = text.replace(OLD, NEW)
with open(PATH, "w") as f:
    f.write(text)
print(f"OK: wrote {PATH} — accept form now offers new-or-existing collection")
