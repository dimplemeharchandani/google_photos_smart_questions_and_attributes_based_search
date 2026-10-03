"""Turn each photo's description and labels into a searchable embedding."""

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config

PHOTOS_PATH = config.DATA_DIR / "photos.json"
EMBEDDINGS_PATH = config.DATA_DIR / "embeddings.npy"
IDS_PATH = config.DATA_DIR / "embedding_ids.json"
INFO_PATH = config.DATA_DIR / "embedding_info.json"

# Spoken names for the fixed labels, in the order they are stored.
LABEL_WORDS = {
    "main_subject": "Mainly of",
    "location_type": "Location",
    "people_count": "People",
    "time_of_day": "Time of day",
    "setting": "Setting",
    "season": "Season",
}

TEST_QUERIES = (
    "old man",
    "food",
    "girl in white frock",
    "dog on the beach",
    "night photos",
)


def everyday_sentence(photo):
    """One sentence of casual search words, or an empty string when there are none."""
    words = photo.get("everyday_words")
    if not isinstance(words, list):
        return ""
    cleaned = []
    for word in words:
        phrase = " ".join(str(word).split())
        if phrase:
            cleaned.append(phrase)
    if not cleaned:
        return ""
    return "Also known as: " + ", ".join(cleaned) + "."


def photo_text(photo):
    """Description, the labels, then everyday words as one extra sentence."""
    description = str(photo.get("description") or "").strip()
    attributes = photo.get("attributes") if isinstance(photo.get("attributes"), dict) else {}
    parts = []
    for key in config.ATTRIBUTES:
        name = LABEL_WORDS.get(key, key.replace("_", " ").capitalize())
        value = attributes.get(key)
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value if str(item).strip())
        if not value:
            value = "unknown"
        parts.append(f"{name}: {value}.")
    labels = " ".join(parts)
    extra = everyday_sentence(photo)
    if description:
        text = f"{description} {labels}"
    else:
        text = labels
    if extra:
        return f"{text} {extra}"
    return text


def fingerprint(text):
    """Short hash of the text, so a later run can see whether it changed."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_photos():
    if not PHOTOS_PATH.exists():
        raise SystemExit(f"No photo file at {PHOTOS_PATH}. Run analyze_photos.py first.")
    with PHOTOS_PATH.open() as handle:
        photos = json.load(handle)
    if not isinstance(photos, list) or not photos:
        raise SystemExit(f"{PHOTOS_PATH} has no photo records.")
    return sorted(photos, key=lambda photo: photo["id"])


def saved_vectors():
    """Photo id -> (vector, fingerprint) from the last run that used this model."""
    if not (EMBEDDINGS_PATH.exists() and IDS_PATH.exists() and INFO_PATH.exists()):
        return {}
    try:
        info = json.loads(INFO_PATH.read_text())
        ids = json.loads(IDS_PATH.read_text())
        matrix = np.load(EMBEDDINGS_PATH)
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    fingerprints = info.get("fingerprints")
    if info.get("model") != config.EMBEDDING_MODEL:
        print(
            f"Saved embeddings used {info.get('model')}. "
            f"Re-embedding every photo with {config.EMBEDDING_MODEL}, "
            "ignoring saved fingerprints.",
            flush=True,
        )
        return {}
    if not isinstance(ids, list) or not isinstance(fingerprints, dict):
        return {}
    if matrix.ndim != 2 or len(ids) != len(matrix):
        return {}
    saved = {}
    for index, photo_id in enumerate(ids):
        saved[photo_id] = (np.asarray(matrix[index], dtype=np.float32), fingerprints.get(str(photo_id)))
    return saved


def normalize(matrix):
    """Make each row length 1, so a dot product is the similarity."""
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def embed_texts(model, texts):
    vectors = model.encode(texts, prompt="", normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vectors, dtype=np.float32)


def build(model):
    """Embed new or changed photos and save vectors, ids, and a small info file."""
    photos = load_photos()
    saved = saved_vectors()
    texts = []
    ids = []
    fingerprints = {}
    reuse = []
    fresh = []

    for photo in photos:
        text = photo_text(photo)
        photo_id = photo["id"]
        digest = fingerprint(text)
        texts.append(text)
        ids.append(photo_id)
        fingerprints[str(photo_id)] = digest
        previous = saved.get(photo_id)
        if previous is not None and previous[1] == digest:
            reuse.append(len(ids) - 1)
        else:
            fresh.append(len(ids) - 1)

    print(
        f"{len(photos)} photos. Reusing {len(reuse)} embeddings. "
        f"Embedding {len(fresh)} new or changed.",
        flush=True,
    )

    width = None
    if reuse:
        width = int(saved[ids[reuse[0]]][0].shape[0])

    fresh_vectors = None
    if fresh:
        print(f"Embedding with {config.EMBEDDING_MODEL}.", flush=True)
        fresh_vectors = embed_texts(model, [texts[index] for index in fresh])
        if fresh_vectors.ndim == 1:
            fresh_vectors = fresh_vectors.reshape(1, -1)
        if width is not None and fresh_vectors.shape[1] != width:
            print("Saved embeddings do not match this model. Embedding every photo.", flush=True)
            fresh = list(range(len(ids)))
            reuse = []
            fresh_vectors = embed_texts(model, texts)

    rows = [None] * len(ids)
    for index in reuse:
        rows[index] = saved[ids[index]][0]
    if fresh_vectors is not None:
        for row, index in enumerate(fresh):
            rows[index] = fresh_vectors[row]

    matrix = normalize(np.vstack(rows))
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    np.save(EMBEDDINGS_PATH, matrix)
    IDS_PATH.write_text(json.dumps(ids, indent=2) + "\n")
    info = {
        "model": config.EMBEDDING_MODEL,
        "built_at": date.today().isoformat(),
        "photo_count": len(ids),
        "fingerprints": fingerprints,
    }
    INFO_PATH.write_text(json.dumps(info, indent=2) + "\n")
    print(
        f"Saved {len(ids)} embeddings to {EMBEDDINGS_PATH.name}, "
        f"{IDS_PATH.name}, and {INFO_PATH.name}.",
        flush=True,
    )
    return photos, matrix


def first_sentence(description):
    text = str(description or "").strip()
    end = text.find(".")
    if end == -1:
        return text
    return text[: end + 1]


def run_search_test(model, photos, matrix):
    """Embed a few searches and print the closest photos."""
    print("\nSearch test (top 5):", flush=True)
    for query in TEST_QUERIES:
        vector = np.asarray(
            model.encode(config.QUERY_PREFIX + query, prompt="", normalize_embeddings=True),
            dtype=np.float32,
        )
        scores = matrix @ vector
        order = np.argsort(-scores)[:5]
        print(f"\n{query}", flush=True)
        for rank, index in enumerate(order, start=1):
            photo = photos[index]
            score = float(scores[index])
            sentence = first_sentence(photo.get("description"))
            print(
                f"  {rank}. id={photo['id']}  path={photo['path']}  score={score:.3f}",
                flush=True,
            )
            print(f"     {sentence}", flush=True)


def main():
    model = SentenceTransformer(config.EMBEDDING_MODEL)
    photos, matrix = build(model)
    run_search_test(model, photos, matrix)


if __name__ == "__main__":
    main()
