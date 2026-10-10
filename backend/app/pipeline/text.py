"""Text normalisation, quote validation and passage selection."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

URL_RE = re.compile(r"https?://[^\s<>\"'）)\]]+", re.IGNORECASE)
_WS = re.compile(r"\s+")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
                         "“": '"', "”": '"', "„": '"', "″": '"',
                         "–": "-", "—": "-", "−": "-", " ": " ", "…": "..."})
_TOKEN = re.compile(r"[\wऀ-ॿ]+", re.UNICODE)
STOPWORDS = set(
    "a an the of to in on for and or is are was were be been by with as at from that this it its into "
    "will has have had not no but than then which who whom what when where why how all any can could "
    "should would may might must shall do does did so such these those their there they them he she his her "
    "you your we our i me my about after before over under also only more most very just".split()
)


def normalize_for_match(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).translate(_QUOTES)
    s = _WS.sub(" ", s).strip().lower()
    return s.strip(" .,;:\"'")


def quote_in_text(quote: str, text: str) -> bool:
    """A quote is valid only if it appears verbatim (modulo whitespace, typographic
    quotes and case) in the retrieved text."""
    q = normalize_for_match(quote)
    if len(q) < 12 or len(q.split()) < 3:
        return False
    return q in normalize_for_match(text)


def extract_urls(text: str) -> list[str]:
    return [u.rstrip(".,;:!?") for u in URL_RE.findall(text)]


def detect_script_language(text: str) -> str:
    deva = sum(1 for ch in text if "ऀ" <= ch <= "ॿ")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    if deva > latin:
        return "devanagari"
    return "latin" if latin else "unknown"


def tokens(text: str) -> list[str]:
    return [t for t in (m.group(0).lower() for m in _TOKEN.finditer(text)) if t not in STOPWORDS and len(t) > 1]


@dataclass
class Passage:
    text: str
    score: float


def split_passages(text: str, target: int = 700) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    out: list[str] = []
    buf = ""
    for p in paras:
        if len(p) > target * 1.6:  # split very long paragraphs on sentence boundaries
            sentences = re.split(r"(?<=[.!?।])\s+", p)
            for s in sentences:
                if len(buf) + len(s) > target and buf:
                    out.append(buf.strip())
                    buf = ""
                buf += s + " "
            continue
        if len(buf) + len(p) > target and buf:
            out.append(buf.strip())
            buf = ""
        buf += p + "\n"
    if buf.strip():
        out.append(buf.strip())
    return [o for o in out if len(o) > 40]


def select_passages(text: str, query_terms: list[str], k: int = 3) -> list[Passage]:
    """Lexical relevance ranking (term overlap weighted by rarity within the document).
    Numbers and named entities in the claim are boosted."""
    candidates = split_passages(text)
    if not candidates:
        return []
    q = [t.lower() for t in query_terms if t]
    qset = set(q)
    doc_freq: dict[str, int] = {}
    toks = [set(tokens(c)) for c in candidates]
    for ts in toks:
        for t in ts & qset:
            doc_freq[t] = doc_freq.get(t, 0) + 1
    n = len(candidates)
    scored = []
    for c, ts in zip(candidates, toks):
        score = 0.0
        for t in ts & qset:
            idf = 1.0 + (n / (1 + doc_freq.get(t, 0)))
            boost = 2.0 if any(ch.isdigit() for ch in t) else 1.0
            score += idf * boost
        scored.append(Passage(c, score / (1 + len(c) / 2000)))
    scored.sort(key=lambda p: p.score, reverse=True)
    return [p for p in scored[:k] if p.score > 0]
