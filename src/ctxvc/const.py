from __future__ import annotations

TOOL_DIR = ".ctxvc"
CONFIG_PATH = "config.json"
REFS_PATH = "refs.json"
SNAPSHOTS_DIR = "snapshots"
OBJECTS_DIR = "objects"
DEFAULT_IGNORES: frozenset[str] = frozenset({TOOL_DIR, ".git", "__pycache__"})
