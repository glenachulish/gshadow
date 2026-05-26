"""Categories: hardcoded for now. Adding a new one means one line here
plus a section card on the home page (templates/index.html).
"""
from typing import Dict, List, NamedTuple


class Category(NamedTuple):
    slug: str
    title: str
    short_title: str
    description: str


CATEGORIES: List[Category] = [
    Category(
        slug="litir-bheag",
        title="An Litir Bheag",
        short_title="Litir Bheag",
        description="Shorter, simpler letters for learners (easier).",
    ),
    Category(
        slug="litir",
        title="Litir do Luchd-ionnsachaidh",
        short_title="Litir",
        description="The full weekly letter for advanced learners.",
    ),
    Category(
        slug="other",
        title="Other Audio",
        short_title="Other",
        description="Anything else: podcasts, songs, recordings, recitations.",
    ),
]

BY_SLUG: Dict[str, Category] = {c.slug: c for c in CATEGORIES}
SLUGS = [c.slug for c in CATEGORIES]


def get(slug: str) -> Category:
    """Returns the category for a slug, or 'other' as the safe default."""
    return BY_SLUG.get(slug, BY_SLUG["other"])


def is_valid(slug: str) -> bool:
    return slug in BY_SLUG
