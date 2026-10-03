"""
booklib.recommend.features – Turns a BookRow into a weighted sparse feature vector.
"""
from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from booklib.db.repository import BookRow

STOP_WORDS = frozenset({
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "cannot", "could", "couldn't",
    "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during",
    "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't",
    "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here",
    "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i",
    "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's",
    "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself",
    "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought",
    "our", "ours", "ourselves", "out", "over", "own", "same", "shan't", "she",
    "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such", "than",
    "that", "that's", "the", "their", "theirs", "them", "themselves", "then", "there",
    "there's", "these", "they", "they'd", "they'll", "they're", "they've", "this",
    "those", "through", "to", "too", "under", "until", "up", "very", "was", "wasn't",
    "we", "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's",
    "when", "when's", "where", "where's", "which", "while", "who", "who's", "whom",
    "why", "why's", "with", "won't", "would", "wouldn't", "you", "you'd", "you'll",
    "you're", "you've", "your", "yours", "yourself", "yourselves", "book", "edition",
    "volume", "guide", "introduction", "first", "second", "third", "complete",
})

_WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?", re.IGNORECASE)


def normalize_term(term: str) -> str:
    """Lowercase and clean string for feature key."""
    return term.strip().lower()


def extract_words(text: str | None) -> list[str]:
    """Tokenize text into lowercase words, skipping stop words and numbers only."""
    if not text:
        return []
    words = []
    for match in _WORD_RE.finditer(text.lower()):
        w = match.group(0)
        if len(w) > 2 and w not in STOP_WORDS and not w.isdigit():
            words.append(w)
    return words


def book_raw_features(book: BookRow) -> dict[str, float]:
    """
    Extract base sparse feature vector for a book before IDF and L2-normalization.
    Weights per Section 5.11:
      author: 3.0
      genre:  2.0
      tag:    2.0
      series: 1.0
      lang:   1.0
      pub:    0.5
      words:  1.0 * TF (title + description)
    """
    feats: dict[str, float] = {}

    # Author
    if book.author:
        authors = re.split(r"[,;&]|\band\b", book.author, flags=re.IGNORECASE)
        for i, auth in enumerate(authors):
            auth_clean = normalize_term(auth)
            if auth_clean:
                # Primary author gets full 3.0, co-authors get 2.0
                w = 3.0 if i == 0 else 2.0
                feats[f"author:{auth_clean}"] = feats.get(f"author:{auth_clean}", 0.0) + w

    # Genre
    if book.genre:
        genres = re.split(r"[,;/]", book.genre)
        for g in genres:
            g_clean = normalize_term(g)
            if g_clean:
                feats[f"genre:{g_clean}"] = feats.get(f"genre:{g_clean}", 0.0) + 2.0

    # Tags
    if book.tags_text:
        tags = re.split(r"[,;]", book.tags_text)
        for t in tags:
            t_clean = normalize_term(t)
            if t_clean:
                feats[f"tag:{t_clean}"] = feats.get(f"tag:{t_clean}", 0.0) + 2.0

    # Series
    if book.series_name:
        s_clean = normalize_term(book.series_name)
        if s_clean:
            feats[f"series:{s_clean}"] = feats.get(f"series:{s_clean}", 0.0) + 1.0

    # Language
    if book.language:
        l_clean = normalize_term(book.language)
        if l_clean:
            feats[f"lang:{l_clean}"] = feats.get(f"lang:{l_clean}", 0.0) + 1.0

    # Publisher
    if book.publisher:
        p_clean = normalize_term(book.publisher)
        if p_clean:
            feats[f"pub:{p_clean}"] = feats.get(f"pub:{p_clean}", 0.0) + 0.5

    # Words (title has 2x weight, description 1x)
    title_words = extract_words(book.title)
    desc_words = extract_words(book.description)
    total_words = len(title_words) * 2 + len(desc_words)

    if total_words > 0:
        word_counts: dict[str, float] = {}
        for w in title_words:
            word_counts[w] = word_counts.get(w, 0.0) + 2.0
        for w in desc_words:
            word_counts[w] = word_counts.get(w, 0.0) + 1.0

        for w, count in word_counts.items():
            tf = count / total_words
            feats[f"word:{w}"] = tf * 1.0

    return feats


def compute_idf(raw_vectors: Iterable[dict[str, float]]) -> dict[str, float]:
    """
    Compute smooth IDF for each feature across a collection of raw feature vectors.
    IDF(f) = ln((1 + N) / (1 + df(f))) + 1.0
    """
    doc_freq: dict[str, int] = {}
    n_docs = 0

    for vec in raw_vectors:
        n_docs += 1
        for feat in vec.keys():
            doc_freq[feat] = doc_freq.get(feat, 0) + 1

    idf: dict[str, float] = {}
    for feat, df in doc_freq.items():
        idf[feat] = math.log((1.0 + n_docs) / (1.0 + df)) + 1.0

    return idf


def apply_idf_and_normalize(
    raw_vec: dict[str, float],
    idf: dict[str, float],
) -> dict[str, float]:
    """
    Multiply feature weights by IDF and L2-normalize to unit length.
    """
    weighted: dict[str, float] = {}
    sum_sq = 0.0

    for feat, val in raw_vec.items():
        w = val * idf.get(feat, 1.0)
        weighted[feat] = w
        sum_sq += w * w

    if sum_sq <= 0:
        return {}

    norm = math.sqrt(sum_sq)
    return {feat: w / norm for feat, w in weighted.items()}
