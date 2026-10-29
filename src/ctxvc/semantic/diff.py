"""Semantic (embedding-based) diffing helpers.

Where a textual diff reports *what bytes changed*, a semantic diff reports *how
much the meaning changed* and can detect renames/moves: a removed item and an
added item whose embeddings are near-identical are surfaced as a rename rather
than an unrelated delete + add.

These functions are pure (no I/O, no printing); callers supply name -> text maps.
"""
from __future__ import annotations

from typing import Any

from ctxvc.semantic.embeddings import cosine_similarity, embed_texts

# Default similarity above which a removed/added pair is treated as a rename.
RENAME_THRESHOLD = 0.85


def classify_change(similarity: float) -> str:
    """Map a similarity score in [0, 1] to a human-readable change magnitude."""
    if similarity >= 0.999:
        return "identical"
    if similarity >= 0.9:
        return "minor"
    if similarity >= 0.7:
        return "moderate"
    if similarity >= 0.4:
        return "major"
    return "rewritten"


def compare_texts(old_text: str, new_text: str) -> dict[str, Any]:
    """Return semantic similarity and change magnitude between two texts."""
    old_vec, new_vec = embed_texts([old_text, new_text])
    similarity = cosine_similarity(old_vec, new_vec)
    return {"similarity": similarity, "change": classify_change(similarity)}


def detect_renames(
    removed: dict[str, str],
    added: dict[str, str],
    threshold: float = RENAME_THRESHOLD,
) -> dict[str, Any]:
    """Greedily pair removed items with added items by embedding similarity.

    Args:
        removed: name -> text for items present only in the base version.
        added: name -> text for items present only in the target version.
        threshold: minimum cosine similarity to consider a pair a rename.

    Returns:
        ``{"renames": [{"from", "to", "similarity"}], "removed": [...], "added": [...]}``
        where the leftover ``removed``/``added`` lists are items that were not paired.
    """
    if not removed or not added:
        return {"renames": [], "removed": list(removed), "added": list(added)}

    removed_names = list(removed)
    added_names = list(added)
    removed_vecs = embed_texts([removed[name] for name in removed_names])
    added_vecs = embed_texts([added[name] for name in added_names])

    candidates: list[tuple[float, str, str]] = []
    for i, r_name in enumerate(removed_names):
        for j, a_name in enumerate(added_names):
            similarity = cosine_similarity(removed_vecs[i], added_vecs[j])
            if similarity >= threshold:
                candidates.append((similarity, r_name, a_name))

    candidates.sort(key=lambda item: item[0], reverse=True)

    used_removed: set[str] = set()
    used_added: set[str] = set()
    renames: list[dict[str, Any]] = []
    for similarity, r_name, a_name in candidates:
        if r_name in used_removed or a_name in used_added:
            continue
        used_removed.add(r_name)
        used_added.add(a_name)
        renames.append({"from": r_name, "to": a_name, "similarity": similarity})

    return {
        "renames": renames,
        "removed": [name for name in removed_names if name not in used_removed],
        "added": [name for name in added_names if name not in used_added],
    }
