"""Run the saved search queries and record whether the right photo is first.

Reads tests/test_queries.csv. Each row is a query and one or more photos
that may come first. An empty expected cell is skipped. NONE means the
search should return no photos. A row passes when any listed photo is
first. Results are printed and saved to data/test_results.csv.
"""

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from search import search

QUERIES_PATH = ROOT / "tests" / "test_queries.csv"
RESULTS_PATH = ROOT / "data" / "test_results.csv"


def photo_path(match):
    """Path of one search result. search() returns (photo, score) pairs."""
    photo = match[0] if isinstance(match, tuple) else match
    return photo["path"]


def rank_of(results, expected):
    """1-based rank of the first result that is this photo, or None."""
    for rank, match in enumerate(results, start=1):
        path = photo_path(match)
        if path == expected or Path(path).name == expected:
            return rank
    return None


def best_rank(results, names):
    """Best rank among the acceptable photos, or None when none were returned."""
    ranks = []
    for name in names:
        rank = rank_of(results, name)
        if rank is not None:
            ranks.append(rank)
    if not ranks:
        return None
    return min(ranks)


def main():
    with QUERIES_PATH.open(newline="") as handle:
        rows = list(csv.reader(handle))
    if rows:
        rows = rows[1:]

    passed = 0
    tested = 0
    saved = []

    for parts in rows:
        if not parts:
            continue
        query = parts[0].strip()
        expected_names = [part.strip() for part in parts[1:] if part.strip()]
        results = search(query)
        top_paths = [photo_path(match) for match in results[:3]]
        top_text = ", ".join(top_paths) if top_paths else "(none)"

        if not expected_names:
            status = "SKIPPED"
            rank_text = "-"
        elif expected_names == ["NONE"]:
            tested += 1
            rank_text = "-"
            if not results:
                status = "PASS"
                passed += 1
            else:
                status = "FAIL"
        else:
            tested += 1
            rank = best_rank(results, expected_names)
            rank_text = "-" if rank is None else str(rank)
            if rank == 1:
                status = "PASS"
                passed += 1
            else:
                status = "FAIL"

        print(f"{query} | {status} | {rank_text} | {top_text}")
        saved.append(
            {
                "query": query,
                "status": status,
                "rank": rank_text,
                "top_3": top_text,
            }
        )

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_PATH.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["query", "status", "rank", "top_3"])
        writer.writeheader()
        writer.writerows(saved)

    print(f"{passed}/{tested} passed")


if __name__ == "__main__":
    main()
