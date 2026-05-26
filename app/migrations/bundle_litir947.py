"""One-off migration: bundle the original 28 Litir Bheag 947 sentence
clips into a collection so they pick up the range/repeat playback UI.

Detects them by looking for standalone clips uploaded near the original
batch. Idempotent: re-running after success does nothing.

Run from the project root on the Pi:
    .venv/bin/python -m app.migrations.bundle_litir947
"""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.db import DB_PATH, init_db  # noqa: E402

# These are the 28 Gaelic sentences of Litir Bheag 947.
SENTENCES_GD = [
    "Tha raineach no bracken fern na plàigh air a' Ghàidhealtachd, nach eil?",
    "Tha i a' còmhdachadh leòidean beinne agus seann talamh-àitich.",
    "Tha i a' mùchadh lusan beaga agus fiùrain craoibhe.",
    "Tha e doirbh coiseachd tro raon far a bheil an raineach àrd agus tiugh.",
    "Agus sin àrainn mhath airson ghartan.",
    "Nach biodh e math dòigh a lorg airson smachd fhaighinn air raineach?",
    "Uill, bha mi a' leughadh seann leabhar an latha eile.",
    "Bha an t-ùghdar ag ainmeachadh trì dòighean airson raineach a mharbhadh.",
    "Anns a' chiad dol a-mach, le bhith ga gearradh sìos gu talamh gu tric.",
    "B' e an dàrna dòigh le bhith a' cur todhar oirre ann am pailteas.",
    "Agus b' e an treas dòigh – an dòigh a b' fheàrr – a bhith a' dòrtadh mùn oirre.",
    "Cha do dh'inns an t-ùghdar dhuinn co-dhiù dhèanadh fir a' bhaile a' chùis le bhith a' mùn air an rainich!",
    "B' e am fear a sgrìobh an cunntas an t-Urramach Iain Lightfoot, eòlaiche-nàdair.",
    "Bha e beò anns an ochdamh linn deug.",
    "Sgrìobh e an leabhar ainmeil Flora Scotica.",
    "Bha Lightfoot dhen bheachd gun robh barrachd feum ann an raineach na bha ann de chron.",
    "Mar eisimpleir, bha cuid a' cleachdadh ghasan rainich mar thughadh air na taighean aca.",
    "Agus bha i feumail air an talamh.",
    "Bha feadhainn a' fàgail raineach uaine gheàrrte air an talamh airson lobhadh, agus bha sin a' cur ri torachas na talmhainn.",
    "Bha i fìor mhath mar thodhar airson buntàta.",
    "Tha Lightfoot ag innse dhuinn gun robh feadhainn a' dèanamh nàdar de shiabann à raineach.",
    "Bha iad a' gearradh an lusa nuair a bha i uaine.",
    "Bha iad ga losgadh.",
    "Bha an luaithre air a measgachadh le uisge airson buill bheaga a dhèanamh.",
    "Bha daoine a' tiormachadh nam ball agus gan cleachdadh airson anart a ghlanadh – an àite siabann.",
    "Bha margaidh ann airson na luaithre, a rèir Lightfoot.",
    "Anns na h-Eileanan Siar, bha gu leòr de dhaoine a' dèanamh prothaid mhòr le bhith a' reic luaithre rainich do dhaoine a bha a' dèanamh siabann no glainne leatha.",
    "Tha mi an dòchas nach eil sibh a' faighinn nan litrichean seo ro thioram!",
]

SLUG = "litir-bheag-947"
TITLE = "Litir Bheag 947 — Lightfoot agus an raineach"
DESCRIPTION = (
    "The 28 sentences of An Litir Bheag 947 from learngaelic.scot, "
    "split into one clip per sentence."
)
SOURCE_URL = "https://learngaelic.scot/litirbheag/litir.jsp?l=947"


def main() -> int:
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    existing = conn.execute(
        "SELECT id FROM collections WHERE slug = ?", (SLUG,)
    ).fetchone()
    if existing:
        print(f"Collection '{SLUG}' already exists (id={existing['id']}). Nothing to do.")
        return 0

    # Find the original 28 clips. They were uploaded one at a time, before
    # the collection_id column existed, so they have collection_id IS NULL.
    # Match by title pattern that includes "Litir Bheag 947" or similar.
    candidates = conn.execute(
        "SELECT id, title, uploaded_at FROM clips "
        "WHERE collection_id IS NULL "
        "AND (title LIKE '%947%' OR title LIKE '%Litir Bheag%' OR title LIKE '%Lightfoot%')"
        "ORDER BY uploaded_at, id"
    ).fetchall()

    if len(candidates) < 28:
        print(
            f"Expected to find 28 clips matching the pattern; found {len(candidates)}.\n"
            "If you uploaded them with different titles, edit this script's title "
            "filter to match what you used. The clips themselves are not deleted; "
            "this script can be re-run safely."
        )
        if len(candidates) == 0:
            return 1
        confirm = input(
            f"Proceed with the {len(candidates)} clips that matched? [y/N]: "
        ).strip().lower()
        if confirm != "y":
            return 1

    # If we have more than 28, use the earliest 28.
    if len(candidates) > 28:
        candidates = candidates[:28]

    # Pick the latest user as the "uploaded_by" for the collection.
    user_row = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
    uploaded_by = user_row["id"] if user_row else None

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO collections (slug, title, description, transcript, notes, "
        "source_url, uploaded_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            SLUG,
            TITLE,
            DESCRIPTION,
            "\n\n".join(SENTENCES_GD),
            None,
            SOURCE_URL,
            uploaded_by,
            now,
        ),
    )
    collection_id = cur.lastrowid

    # Update each clip: set collection_id, position, and (if we have a
    # sentence text) overwrite the description with the Gaelic sentence.
    for pos, clip in enumerate(candidates, start=1):
        sentence = SENTENCES_GD[pos - 1] if pos - 1 < len(SENTENCES_GD) else ""
        conn.execute(
            "UPDATE clips SET collection_id = ?, position = ?, "
            "title = ?, description = ? "
            "WHERE id = ?",
            (
                collection_id,
                pos,
                f"Sentence {pos}",
                sentence,
                clip["id"],
            ),
        )
    conn.commit()
    print(
        f"Bundled {len(candidates)} clips into collection '{SLUG}' "
        f"(id={collection_id}). Visit /c/{SLUG} on the site to see it."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
