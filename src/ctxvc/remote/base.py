"""Pluggable remote backends for pushing/pulling versioned context.

A remote is the *system of record* for shared context: a content-addressed
object store (blobs), an immutable snapshot store, and a set of mutable refs
(branch -> snapshot id) that support **compare-and-swap** so concurrent pushes
cannot silently clobber each other.

Backends only need to implement these primitives; the push/pull negotiation and
fast-forward safety live in :mod:`ctxvc.remote.sync`, so every backend behaves
identically.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class Remote(ABC):
    """Abstract transport for content-addressed objects, snapshots, and refs."""

    name: str

    # --- objects (content-addressed blobs, keyed by sha256 of the text) -------
    @abstractmethod
    def has_object(self, content_hash: str) -> bool:
        """Return True if an object with this hash already exists remotely."""

    @abstractmethod
    def get_object(self, content_hash: str) -> str:
        """Return the object's text content. Raises if absent."""

    @abstractmethod
    def put_object(self, content_hash: str, content: str) -> None:
        """Store text content under its hash. Must be idempotent."""

    # --- snapshots (immutable JSON bodies, keyed by id) ----------------------
    @abstractmethod
    def has_snapshot(self, snapshot_id: str) -> bool:
        ...

    @abstractmethod
    def get_snapshot(self, snapshot_id: str) -> dict[str, object]:
        """Return the snapshot body. Raises if absent."""

    @abstractmethod
    def put_snapshot(self, snapshot_id: str, payload: dict[str, object]) -> None:
        """Store a snapshot body. Must be idempotent (snapshots are immutable)."""

    # --- refs (mutable pointers; require compare-and-swap) -------------------
    @abstractmethod
    def get_ref(self, name: str) -> str | None:
        """Return the snapshot id a ref points at, or None if it does not exist."""

    @abstractmethod
    def list_refs(self) -> dict[str, str | None]:
        ...

    @abstractmethod
    def update_ref(self, name: str, expected: str | None, new: str | None) -> bool:
        """Atomically set ``name`` to ``new`` only if it currently equals ``expected``.

        Returns True on success, False if the current value differed (the caller
        lost a race and should re-read / pull). ``new=None`` deletes the ref.
        """
