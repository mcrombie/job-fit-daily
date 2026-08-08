from __future__ import annotations

import html
import math
import re
from collections import Counter
from html.parser import HTMLParser
from typing import Iterable


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "li", "div", "section", "h1", "h2", "h3", "h4"}:
            self.parts.append(" ")

    def get_text(self) -> str:
        return " ".join(self.parts)


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(value)
        parser.close()
        text = parser.get_text()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", value)
    return normalize_space(html.unescape(text))


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalized(value: str) -> str:
    lowered = html.unescape(value).lower()
    lowered = lowered.replace("’", "'").replace("–", "-").replace("—", "-")
    return normalize_space(lowered)


_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "in", "is", "it",
    "of", "on", "or", "our", "that", "the", "their", "this", "to", "we", "will", "with", "you", "your",
    "who", "what", "when", "where", "how", "into", "about", "can", "may", "but", "not", "all", "any",
    "more", "than", "such", "using", "use", "work", "role", "team", "job", "position", "company",
}

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#.\-/]{1,}")


def tokenize(value: str) -> list[str]:
    tokens = _TOKEN_RE.findall(normalized(value))
    return [token.strip(".-/") for token in tokens if token not in _STOPWORDS and len(token.strip(".-/")) > 1]


def contains_phrase(text: str, phrase: str) -> bool:
    return normalized(phrase) in normalized(text)


def phrase_hits(text: str, phrases: Iterable[str]) -> list[str]:
    haystack = normalized(text)
    return [phrase for phrase in phrases if normalized(str(phrase)) in haystack]


def required_years(text: str) -> int | None:
    """Return the largest apparent minimum years requirement in a description."""
    cleaned = normalized(text)
    patterns = (
        r"(?:at least|minimum of|minimum)\s+(\d{1,2})\s*\+?\s*(?:years?|yrs?)",
        r"(\d{1,2})\s*\+\s*(?:years?|yrs?)",
        r"(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\s*(?:years?|yrs?)",
        r"(\d{1,2})\s+(?:years?|yrs?)\s+(?:of\s+)?(?:professional|relevant|industry|software|development|experience)",
    )
    minima: list[int] = []
    for pattern in patterns:
        for match in re.finditer(pattern, cleaned):
            try:
                minima.append(int(match.group(1)))
            except (TypeError, ValueError):
                continue
    plausible = [value for value in minima if 0 < value < 25]
    return max(plausible) if plausible else None


def tfidf_similarities(candidate_text: str, documents: list[str]) -> list[float]:
    """Small dependency-free TF-IDF cosine implementation."""
    if not documents:
        return []
    candidate_tokens = tokenize(candidate_text)
    document_tokens = [tokenize(document) for document in documents]
    all_docs = [candidate_tokens, *document_tokens]
    document_frequency: Counter[str] = Counter()
    for tokens in all_docs:
        document_frequency.update(set(tokens))
    document_count = len(all_docs)

    def vector(tokens: list[str]) -> dict[str, float]:
        counts = Counter(tokens)
        values: dict[str, float] = {}
        for term, count in counts.items():
            tf = 1.0 + math.log(count)
            idf = math.log((document_count + 1) / (document_frequency[term] + 1)) + 1.0
            values[term] = tf * idf
        return values

    candidate_vector = vector(candidate_tokens)
    candidate_norm = math.sqrt(sum(value * value for value in candidate_vector.values()))
    if not candidate_norm:
        return [0.0] * len(documents)

    results: list[float] = []
    for tokens in document_tokens:
        doc_vector = vector(tokens)
        doc_norm = math.sqrt(sum(value * value for value in doc_vector.values()))
        if not doc_norm:
            results.append(0.0)
            continue
        dot = sum(value * doc_vector.get(term, 0.0) for term, value in candidate_vector.items())
        results.append(dot / (candidate_norm * doc_norm))
    return results


def excerpt(text: str, limit: int = 360) -> str:
    cleaned = normalize_space(text)
    if len(cleaned) <= limit:
        return cleaned
    shortened = cleaned[: limit - 1].rsplit(" ", 1)[0]
    return shortened + "…"
