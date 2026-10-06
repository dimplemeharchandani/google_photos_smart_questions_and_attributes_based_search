"""Find photos whose saved description is close to a short search.

The app and the test runner both call search(). The scoring rules live
here so a test sees the same ordered list the page shows.

A search first takes the closest embedding matches, adds any photo whose
label the search mentioned, then lets the re-ranker order that list.
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
from sentence_transformers import CrossEncoder, SentenceTransformer
from torch.nn import Identity

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config
from build_embeddings import photo_text

PHOTOS_PATH = config.DATA_DIR / "photos.json"
EMBEDDINGS_PATH = config.DATA_DIR / "embeddings.npy"
IDS_PATH = config.DATA_DIR / "embedding_ids.json"
INFO_PATH = config.DATA_DIR / "embedding_info.json"

# The models are heavy, so the first search loads them and later searches reuse them.
_model = None
_reranker = None
_label_patterns = None


def clean_text(text):
    """Lowercase the search and collapse extra spaces."""
    return " ".join(text.lower().split())


def load_library():
    """Load photos and line each one up with its embedding row.

    Returns (photos, matrix, saved_model, problem).
    problem is a short message when the files cannot be used.
    """
    missing = [
        path.name
        for path in (PHOTOS_PATH, EMBEDDINGS_PATH, IDS_PATH, INFO_PATH)
        if not path.exists()
    ]
    if missing:
        names = ", ".join(missing)
        return None, None, None, f"Missing {names}. Run build_embeddings.py, then refresh this page."

    photos = json.loads(PHOTOS_PATH.read_text())
    ids = json.loads(IDS_PATH.read_text())
    info = json.loads(INFO_PATH.read_text())
    matrix = np.load(EMBEDDINGS_PATH)

    if not isinstance(photos, list) or not isinstance(ids, list):
        return None, None, None, "The photo files are not in the expected shape. Re-run build_embeddings.py."
    if matrix.ndim != 2 or len(ids) != len(matrix):
        return None, None, None, "The embedding files do not line up. Re-run build_embeddings.py, then refresh this page."

    by_id = {photo["id"]: photo for photo in photos}
    kept = []
    rows = []
    for index, photo_id in enumerate(ids):
        photo = by_id.get(photo_id)
        if photo is None:
            continue
        kept.append(photo)
        rows.append(matrix[index])

    if not rows:
        return None, None, None, "No photos match the saved embeddings. Re-run build_embeddings.py."

    aligned = np.asarray(np.vstack(rows), dtype=np.float32)
    return kept, aligned, info.get("model"), None


def load_model():
    """Load the embedding model once. Later searches reuse it."""
    global _model
    if _model is None:
        _model = SentenceTransformer(config.EMBEDDING_MODEL)
    return _model


def embed_query(model, text):
    """Turn the search text into one vector of length 1.

    A dot product with a photo embedding is then the similarity.
    """
    vector = np.asarray(
        model.encode(text, prompt="", normalize_embeddings=True, show_progress_bar=False),
        dtype=np.float32,
    ).reshape(-1)
    length = float(np.linalg.norm(vector))
    if length == 0:
        return vector
    return vector / length


def expand_free_text(text):
    """Rewrite casual words (config.FREE_TEXT_SYNONYMS) before scoring.

    Only affects the embedding + re-ranker text, so a search for "frock"
    is scored as if it said "dress" without changing what the search box
    showed or what mentioned_labels sees.
    """
    words = text.split(" ")
    rewritten = [config.FREE_TEXT_SYNONYMS.get(word, word) for word in words]
    return " ".join(rewritten)


def fold_text(text):
    """Lowercase, drop accents, and collapse spaces. café and cafe then match."""
    normalized = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return clean_text(stripped)


def label_patterns():
    """Compiled phrases for every label value, longest phrase first."""
    global _label_patterns
    if _label_patterns is not None:
        return _label_patterns

    patterns = []
    for label, allowed in config.ATTRIBUTES.items():
        groups = config.LABEL_SYNONYMS.get(label, {})
        if not isinstance(groups, dict):
            groups = {}
        for value in allowed:
            seen = set()
            phrases = []
            listed = groups.get(value, [])
            if isinstance(listed, str):
                listed = [listed]
            if not isinstance(listed, (list, tuple)):
                listed = []
            for phrase in list(listed) + [value]:
                folded = fold_text(str(phrase))
                if not folded or folded in seen:
                    continue
                seen.add(folded)
                phrases.append(folded)
            phrases.sort(key=len, reverse=True)
            compiled = [
                re.compile(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)")
                for phrase in phrases
            ]
            patterns.append((label, value, compiled))
    _label_patterns = patterns
    return patterns


def mentioned_labels(text):
    """Label values whose name or synonym appears in the search."""
    folded = fold_text(text)
    found = []
    for label, value, patterns in label_patterns():
        if any(pattern.search(folded) for pattern in patterns):
            found.append((label, value))
    return found


def first_stage(photos, similarities):
    """The closest embedding matches, at most RERANK_TOP_N of them."""
    if len(photos) == 0:
        return []
    order = np.argsort(-similarities)
    limit = max(int(config.RERANK_TOP_N), 0)
    return [photos[int(index)] for index in order[:limit]]


def add_label_matches(text, photos, candidates):
    """Add every photo with a label the search mentioned, even a weak embedding."""
    wanted = mentioned_labels(text)
    if not wanted:
        return candidates
    seen = {photo["id"] for photo in candidates}
    combined = list(candidates)
    for photo in photos:
        if photo["id"] in seen:
            continue
        attributes = photo.get("attributes") if isinstance(photo.get("attributes"), dict) else {}
        for label, value in wanted:
            if attributes.get(label) == value:
                combined.append(photo)
                seen.add(photo["id"])
                break
    return combined


def load_reranker():
    """Load the re-ranker once. Scores stay raw: no sigmoid."""
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder(config.RERANK_MODEL, activation_fn=Identity())
    return _reranker


def rerank_scores(query, passages):
    """Raw re-ranker score for each passage, in the same order."""
    if not passages:
        return []
    pairs = [(query, passage) for passage in passages]
    scores = load_reranker().predict(
        pairs,
        activation_fn=Identity(),
        show_progress_bar=False,
    )
    return [float(score) for score in np.asarray(scores, dtype=np.float32).reshape(-1)]


def mixed_score(raw_score, similarity, low, high):
    """Blend a raw re-ranker score with the first-stage similarity.

    The re-ranker score is stretched to 0–1 across this search's candidates.
    The similarity is already about 0–1. The weights live in config.py.
    """
    span = high - low
    scaled = 1.0 if span == 0 else (raw_score - low) / span
    return (
        float(config.RERANK_WEIGHT) * scaled
        + float(config.SIMILARITY_WEIGHT) * similarity
    )


def search(query):
    """Return the photos the app would show for this query, best first.

    Each item is a (photo, score) pair. The score is the mixed final score.
    A photo whose raw re-ranker score is below RERANK_MIN_SCORE is left out.
    If none remain, the list is empty and the app says no close matches were found.
    An empty query returns no photos.
    """
    text = clean_text(query)
    if not text:
        return []

    photos, matrix, saved_model, problem = load_library()
    if problem:
        raise RuntimeError(problem)
    if saved_model != config.EMBEDDING_MODEL:
        built_with = saved_model or "an unknown model"
        raise RuntimeError(
            f"These embeddings were built with {built_with}, "
            f"but search uses {config.EMBEDDING_MODEL}."
        )

    scored_text = expand_free_text(text)
    query_vector = embed_query(load_model(), config.QUERY_PREFIX + scored_text)
    # §2.8: Apple's Accelerate BLAS raises spurious divide-by-zero /
    # overflow / invalid-value warnings on this matmul on Apple Silicon
    # (a known NumPy + Accelerate quirk, unrelated to this data - checked
    # by hand that neither matrix nor query_vector contain NaN/Inf, and
    # that similarities never does either). Silenced locally, around
    # only this call, rather than globally.
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        similarities = matrix @ query_vector
    if len(similarities) == 0:
        return []
    similarity_by_id = {
        photos[index]["id"]: float(similarities[index]) for index in range(len(photos))
    }

    candidates = first_stage(photos, similarities)
    candidates = add_label_matches(text, photos, candidates)
    if not candidates:
        return []

    raw_scores = rerank_scores(scored_text, [photo_text(photo) for photo in candidates])
    low = min(raw_scores)
    high = max(raw_scores)
    floor = float(config.RERANK_MIN_SCORE)
    ranked = []
    for photo, raw_score in zip(candidates, raw_scores):
        if raw_score < floor:
            continue
        final = mixed_score(raw_score, similarity_by_id[photo["id"]], low, high)
        ranked.append((photo, final))
    ranked.sort(key=lambda item: (-item[1], item[0].get("id", 0)))
    return ranked
