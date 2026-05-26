"""Adapters for fetching audio + transcript from supported sites.

Currently supports learngaelic.scot (both Litir Bheag and Litir).
"""
import html as html_lib
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class FetchResult:
    """Normalised result an adapter returns to the import pipeline."""
    audio_url: str
    title_en: str
    title_gd: str
    transcript_gd: str
    transcript_en: str
    sentences_gd: List[str] = field(default_factory=list)
    sentences_en: List[str] = field(default_factory=list)
    suggested_slug: str = ""
    source_url: str = ""
    # New in v2.3 — for interview-style content from Look@LearnGaelic and
    # Watch Gaelic. When split_mode == "speakers", the importer uses a
    # longer minimum-pause threshold so cuts fall at speaker changes,
    # and turns_gd is the per-clip text instead of sentences_gd.
    split_mode: str = "sentences"   # 'sentences' | 'speakers'
    turns_gd: List[str] = field(default_factory=list)
    turns_en: List[str] = field(default_factory=list)
    is_video: bool = False  # True if audio_url points to an MP4
    suggested_category: str = "other"


class AdapterError(Exception):
    """Raised when an adapter cannot extract the expected content."""


def _http_get(url: str, timeout: int = 30) -> str:
    """Fetch a URL and return text. Pretends to be a normal browser."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
            "Accept-Language": "en-GB,en;q=0.5",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _split_sentences(text: str) -> List[str]:
    """Split a paragraph of Gaelic/English prose into sentences.

    Conservative: splits on `.`, `?`, `!` followed by whitespace + capital
    letter, taking care of common abbreviations (no perfect solution
    exists). Works well for the prose style of these letters.
    """
    text = text.strip()
    if not text:
        return []
    # Normalise whitespace and curly punctuation.
    text = re.sub(r"[\u00a0\s]+", " ", text)
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    # Split on sentence-ending punctuation followed by space + capital.
    # The lookbehind keeps the punctuation attached to the prior sentence.
    parts = re.split(r"(?<=[.?!])\s+(?=[A-Z\u00C0-\u017F])", text)
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# learngaelic.scot adapter
# ---------------------------------------------------------------------------
_LG_HOST_RE = re.compile(
    r"^https?://(?:www\.)?learngaelic\.scot/(litir|litirbheag)/litir\.jsp\?l=(\d+)",
    re.IGNORECASE,
)


def _learngaelic_audio_url(series: str, num: int) -> str:
    """Audio is hosted on a stable CloudFront path keyed by series and number."""
    if series == "litirbheag":
        return f"https://d29gjwrcc23kr6.cloudfront.net/lg-litirbheag/litirbheag{num:04d}.caf"
    return f"https://d29gjwrcc23kr6.cloudfront.net/lg-litir/litir{num:04d}.caf"


# Match the <h1> at the top of the page.
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.DOTALL | re.IGNORECASE)
# Match the H3 (transcript heading) and its following paragraphs until next H or section.
_SECTION_RE = re.compile(
    r"<h3[^>]*>\s*(?P<heading>[^<]+?)\s*</h3>(?P<body>.*?)(?=<h3|<h2|<section|<div\s+class=\"linkstxt\")",
    re.DOTALL | re.IGNORECASE,
)
_P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    """Remove tags, decode all HTML entities, collapse whitespace."""
    text = _TAG_RE.sub("", html)
    text = html_lib.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _paragraphs_in_section(body_html: str) -> List[str]:
    """Pull <p> contents from a section of HTML, in order."""
    return [_strip_html(m.group(1)) for m in _P_RE.finditer(body_html)]


def fetch_learngaelic(url: str) -> FetchResult:
    """Adapter for learngaelic.scot Litir Bheag and Litir.

    URL must look like:
      https://learngaelic.scot/litir/litir.jsp?l=1381
      https://learngaelic.scot/litirbheag/litir.jsp?l=1040
    """
    m = _LG_HOST_RE.match(url.strip())
    if not m:
        raise AdapterError(
            "URL doesn't match the expected pattern "
            "'https://learngaelic.scot/(litir|litirbheag)/litir.jsp?l=N'."
        )
    series = m.group(1).lower()
    num = int(m.group(2))
    audio_url = _learngaelic_audio_url(series, num)

    html = _http_get(url)

    # Page title: e.g. "John Matheson of Shieldaig (2)  (An Litir Bheag)"
    # is a meta title; we want the H1 (English title) and the first H3 in
    # the Gaelic block (Gaelic title is also an H3 like the transcript
    # heading on this site — it duplicates).
    # The H1 contains both English and Gaelic titles concatenated, but
    # splitting reliably is tricky (Gaelic words with accents can appear
    # in either half — e.g. proper nouns). Instead, we take titles from
    # the H3 transcript headings below, which are unambiguously one
    # language each. The H1 is only used as a fallback.
    h1_fallback = ""
    for m in _H1_RE.finditer(html):
        h1 = _strip_html(m.group(1))
        if h1 and not h1.startswith("LearnGaelic"):
            h1_fallback = h1
            break

    title_en = ""
    title_gd = ""
    if not title_en:
        title_en = f"Litir {num}" if series == "litir" else f"Litir Bheag {num}"

    # Sections: there are usually two H3s with the same Gaelic heading
    # (the page renders the Gaelic transcript twice on this site). We
    # take the first English-titled H3 as the English transcript, and
    # the first Gaelic-titled H3 as the Gaelic transcript.
    # Section bodies are matched by H3 + paragraphs. We classify each
    # section as Gaelic / English by counting Gaelic-only characters in
    # the BODY (not the heading) — proper-noun headings like "Uilleam
    # Hare" / "William Hare" don't reliably tell us the language.
    en_paras: List[str] = []
    gd_paras: List[str] = []
    seen_gd_heading = ""
    seen_en_heading = ""

    def _gaelic_density(text: str) -> float:
        """Fraction of letters that are accented vowels typical of Gaelic.
        Robust signal: Gaelic prose averages ~3-6%; English ~0%."""
        if not text:
            return 0.0
        letters = sum(1 for c in text if c.isalpha())
        if letters == 0:
            return 0.0
        gd = sum(1 for c in text if c in "àèìòùÀÈÌÒÙâêîôûÂÊÎÔÛ")
        return gd / letters

    # Paragraphs that mark the END of the audio transcript proper. After
    # any of these on a Litir page, the rest is vocab notes / language
    # commentary and is NOT in the audio.
    _VOCAB_MARKERS_RE = re.compile(
        r"^(Faclan na Litreach|Abairtean na Litreach|Puing-?(ch|gh|gr)|"
        r"Gnàthas-cainnt|Gn&agrave;thas-cainnt|"
        r"Tha .Litir|Tha \"Litir|Tha &ldquo;Litir)",
        re.IGNORECASE,
    )

    def _trim_at_vocab(paras: List[str]) -> List[str]:
        out = []
        for p in paras:
            if _VOCAB_MARKERS_RE.match(p.strip()):
                break
            out.append(p)
        return out

    for sm in _SECTION_RE.finditer(html):
        heading = _strip_html(sm.group("heading"))
        body = sm.group("body")
        paras = [p for p in _paragraphs_in_section(body) if p]
        if not paras:
            continue
        # Skip the trailing "PDF" section and similar utility blocks.
        if heading.strip().lower() in ("pdf", "podcast", ""):
            continue
        # Trim trailing vocabulary / language-notes paragraphs.
        paras = _trim_at_vocab(paras)
        if not paras:
            continue
        # Classify by body content density (>1% accented = Gaelic).
        combined_body = " ".join(paras)
        is_gaelic = _gaelic_density(combined_body) > 0.01
        if is_gaelic and not gd_paras:
            gd_paras = paras
            seen_gd_heading = heading
        elif not is_gaelic and not en_paras:
            en_paras = paras
            seen_en_heading = heading

    if not gd_paras:
        raise AdapterError(
            "Could not find the Gaelic transcript on the page. The site "
            "structure may have changed."
        )

    # Use the H3 headings as titles. They're unambiguously single-language
    # on these pages.
    title_en = seen_en_heading or h1_fallback or (
        f"Litir {num}" if series == "litir" else f"Litir Bheag {num}"
    )
    title_gd = seen_gd_heading or h1_fallback

    transcript_gd = "\n\n".join(gd_paras)
    transcript_en = "\n\n".join(en_paras)

    # Sentence-split the Gaelic transcript. Each paragraph splits
    # independently so we don't merge sentences across paragraph breaks.
    sentences_gd: List[str] = []
    for p in gd_paras:
        sentences_gd.extend(_split_sentences(p))
    sentences_en: List[str] = []
    for p in en_paras:
        sentences_en.extend(_split_sentences(p))

    slug_prefix = "litir-bheag" if series == "litirbheag" else "litir"
    return FetchResult(
        audio_url=audio_url,
        title_en=title_en,
        title_gd=title_gd,
        transcript_gd=transcript_gd,
        transcript_en=transcript_en,
        sentences_gd=sentences_gd,
        sentences_en=sentences_en,
        suggested_slug=f"{slug_prefix}-{num}",
        source_url=url,
    )


# ---------------------------------------------------------------------------
# learngaelic.scot Look + Watch adapter (interview-style video pages)
# ---------------------------------------------------------------------------
_LOOK_HOST_RE = re.compile(
    r"^https?://(?:www\.)?learngaelic\.scot/look/look\.jsp\?(?:v|b)=([\w-]+)",
    re.IGNORECASE,
)
_WATCH_HOST_RE = re.compile(
    r"^https?://(?:www\.)?learngaelic\.scot/watch/watch\.jsp\?v=([\w-]+)",
    re.IGNORECASE,
)
# Match any MP4 URL embedded in the page. learngaelic.scot uses S3 for
# Look videos and CloudFront for Watch.
_MP4_RE = re.compile(
    r"https?://[^\s\"'<>]+?\.mp4\b",
    re.IGNORECASE,
)
# A speaker turn looks like:    [Karen Elder] body text...
# Robust to bracketed paragraph-leading markers like [SARAH] or [MUIREALL].
_TURN_RE = re.compile(
    r"^\s*\[(?P<speaker>[^\]\n]{1,80})\]\s*(?P<text>.*)$",
    re.DOTALL,
)


def _split_turns(paras: List[str]) -> List[str]:
    """For interview transcripts. Take paragraphs and group them into
    speaker turns. Paragraphs without a [Speaker] tag merge into the
    previous turn. Leading paragraphs that have no preceding [Speaker]
    are dropped (they're typically "Presenter: …" prelude text).
    Returns: list of plain-text turns ('[Speaker] body...' format)."""
    turns: List[str] = []
    current: List[str] = []  # accumulating one turn's lines
    started = False  # have we seen our first [Speaker] tag yet?
    for p in paras:
        p = p.strip()
        if not p:
            continue
        m = _TURN_RE.match(p)
        if m:
            # Flush previous turn.
            if current:
                turns.append(" ".join(current))
                current = []
            speaker = m.group("speaker").strip()
            text = m.group("text").strip()
            current.append(f"[{speaker}] {text}" if text else f"[{speaker}]")
            started = True
        else:
            # Continuation of prior turn — but only if we've started.
            if started:
                current.append(p)
            # Otherwise: prelude text, drop it.
    if current:
        turns.append(" ".join(current))
    return turns


def fetch_learngaelic_video(url: str) -> FetchResult:
    """Adapter for Look@LearnGaelic and Watch Gaelic. Same shape: an MP4
    video plus a Gaelic and English transcript formatted as speaker turns.
    """
    url = url.strip()
    look_m = _LOOK_HOST_RE.match(url)
    watch_m = _WATCH_HOST_RE.match(url)
    if not (look_m or watch_m):
        raise AdapterError("URL doesn't match the expected Look or Watch pattern.")
    series = "look" if look_m else "watch"
    item_id = (look_m or watch_m).group(1)

    html = _http_get(url)

    # The MP4 URL is in the page body. Take the first one.
    mp4_match = _MP4_RE.search(html)
    if not mp4_match:
        raise AdapterError(
            "Could not find an .mp4 URL on the page. The site structure may "
            "have changed."
        )
    video_url = mp4_match.group(0)

    # H1 — bilingual title block. Use it as a fallback.
    h1_fallback = ""
    for m in _H1_RE.finditer(html):
        h1 = _strip_html(m.group(1))
        if h1 and not h1.startswith("LearnGaelic"):
            h1_fallback = h1
            break

    # Scan H3 sections, classify by Gaelic density, take FIRST Gaelic +
    # FIRST English block (the pages tend to render each twice).
    en_paras: List[str] = []
    gd_paras: List[str] = []
    seen_gd_heading = ""
    seen_en_heading = ""

    for sm in _SECTION_RE.finditer(html):
        heading = _strip_html(sm.group("heading"))
        body = sm.group("body")
        paras = [p for p in _paragraphs_in_section(body) if p]
        if not paras:
            continue
        # Skip utility headings.
        lc = heading.strip().lower()
        if lc in ("pdf", "podcast", "vocabulary", "briathrachas", ""):
            continue
        # Skip single-word vocabulary blocks (Watch pages list a
        # vocabulary glossary as one H3 per word).
        if len(heading.split()) <= 2 and any(
            p.strip().startswith("*") and "*" in p.strip()[1:] for p in paras
        ):
            continue
        combined = " ".join(paras)
        if not combined.strip():
            continue
        density = sum(1 for c in combined if c in "àèìòùÀÈÌÒÙâêîôûÂÊÎÔÛ") / max(
            1, sum(1 for c in combined if c.isalpha())
        )
        is_gaelic = density > 0.01
        if is_gaelic and not gd_paras:
            gd_paras = paras
            seen_gd_heading = heading
        elif not is_gaelic and not en_paras:
            # Skip the "Presenter: ..." sub-block on Look pages — too short.
            if len(combined) > 100:
                en_paras = paras
                seen_en_heading = heading

    if not gd_paras:
        raise AdapterError(
            "Could not find the Gaelic transcript on the page. The site "
            "structure may have changed."
        )

    # Group paragraphs into speaker turns.
    turns_gd = _split_turns(gd_paras)
    turns_en = _split_turns(en_paras) if en_paras else []

    if len(turns_gd) < 2:
        raise AdapterError(
            f"Found only {len(turns_gd)} speaker turn(s) in the transcript. "
            "Cannot split into clips. The page may not be an interview-style "
            "transcript."
        )

    title_en = seen_en_heading or h1_fallback or f"{series.title()} {item_id}"
    title_gd = seen_gd_heading or h1_fallback

    transcript_gd = "\n\n".join(gd_paras)
    transcript_en = "\n\n".join(en_paras)

    slug_prefix = "look" if series == "look" else "watch"
    return FetchResult(
        audio_url=video_url,
        title_en=title_en,
        title_gd=title_gd,
        transcript_gd=transcript_gd,
        transcript_en=transcript_en,
        sentences_gd=[],   # not applicable
        sentences_en=[],
        turns_gd=turns_gd,
        turns_en=turns_en,
        suggested_slug=f"{slug_prefix}-{item_id.lower()}",
        source_url=url,
        split_mode="speakers",
        is_video=True,
        suggested_category="other",
    )


# ---------------------------------------------------------------------------
# Adapter dispatch
# ---------------------------------------------------------------------------
def fetch(url: str) -> FetchResult:
    """Choose the right adapter for the URL. Raises AdapterError if none."""
    u = url.strip()
    if _LG_HOST_RE.match(u):
        r = fetch_learngaelic(u)
        # Backfill suggested_category for the older Litir adapter.
        if r.suggested_slug.startswith("litir-bheag"):
            r.suggested_category = "litir-bheag"
        elif r.suggested_slug.startswith("litir"):
            r.suggested_category = "litir"
        return r
    if _LOOK_HOST_RE.match(u) or _WATCH_HOST_RE.match(u):
        return fetch_learngaelic_video(u)
    raise AdapterError(
        f"No adapter knows how to handle {url!r}. Currently supported: "
        "learngaelic.scot Litir, Litir Bheag, Look, and Watch Gaelic pages. "
        "For other audio, use the Mac splitter script (mac-splitter.py)."
    )


def is_supported(url: str) -> bool:
    """True if any adapter can handle this URL."""
    u = url.strip()
    return bool(_LG_HOST_RE.match(u) or _LOOK_HOST_RE.match(u) or _WATCH_HOST_RE.match(u))
