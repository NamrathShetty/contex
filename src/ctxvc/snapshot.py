from __future__ import annotations

import difflib
from pathlib import Path
from typing import Iterable

from ctxvc.config import get_agent_path, resolve_within_repo
from ctxvc.const import DEFAULT_IGNORES
from ctxvc.errors import CtxvcError
from ctxvc.store import hash_text, read_object, resolve_entry_text


def collect_files(repo_root: Path, raw_paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for raw_path in raw_paths:
        candidate = (
            (repo_root / raw_path).resolve()
            if not raw_path.is_absolute()
            else raw_path.resolve()
        )
        if not candidate.exists():
            raise CtxvcError(f"path does not exist: {raw_path}")
        if candidate.is_dir():
            for child in sorted(candidate.rglob("*")):
                if child.is_dir() or is_ignored(repo_root, child):
                    continue
                if child not in seen:
                    files.append(child)
                    seen.add(child)
        else:
            if is_ignored(repo_root, candidate):
                continue
            if candidate not in seen:
                files.append(candidate)
                seen.add(candidate)
    return sorted(files)


def is_ignored(repo_root: Path, file_path: Path) -> bool:
    parts = file_path.relative_to(repo_root).parts
    return any(part in DEFAULT_IGNORES for part in parts)


def build_working_index(repo_root: Path, files: Iterable[Path]) -> dict[str, dict[str, object]]:
    index: dict[str, dict[str, object]] = {}
    for file_path in files:
        rel_path = file_path.relative_to(repo_root).as_posix()
        content = file_path.read_text(encoding="utf-8")
        index[rel_path] = {
            "path": rel_path,
            "content_hash": hash_text(content),
            "size": len(content.encode("utf-8")),
            "source_path": str(file_path),
        }
    return index


def compare_indices(
    base_index: dict[str, dict[str, object]],
    target_index: dict[str, dict[str, object]],
) -> list[tuple[str, str]]:
    changes: list[tuple[str, str]] = []
    for path in sorted(set(base_index) | set(target_index)):
        if path not in base_index:
            changes.append(("A", path))
        elif path not in target_index:
            changes.append(("D", path))
        elif base_index[path]["content_hash"] != target_index[path]["content_hash"]:
            changes.append(("M", path))
    return changes


def filter_index_by_prefixes(
    index: dict[str, dict[str, object]],
    prefixes: list[str],
) -> dict[str, dict[str, object]]:
    if not prefixes:
        return index
    result: dict[str, dict[str, object]] = {}
    for path, entry in index.items():
        for prefix in prefixes:
            if path == prefix or path.startswith(prefix.rstrip("/") + "/"):
                result[path] = entry
                break
    return result


def as_repo_relative(repo_root: Path, raw_path: Path) -> str:
    return resolve_within_repo(repo_root, raw_path).relative_to(repo_root).as_posix()


def resolve_snapshot_targets(
    repo_root: Path,
    tool_root: Path,
    raw_paths: list[str],
    agent_name: str | None,
) -> tuple[list[Path], list[str]]:
    if agent_name and raw_paths:
        raise CtxvcError("use either paths or --agent, not both")
    if agent_name:
        return [get_agent_path(repo_root, tool_root, agent_name)], [agent_name]
    if raw_paths:
        return [Path(p) for p in raw_paths], []
    raise CtxvcError("provide at least one path or use --agent")


def resolve_status_targets(
    repo_root: Path,
    tool_root: Path,
    raw_paths: list[str],
    agent_name: str | None,
) -> list[Path]:
    if agent_name and raw_paths:
        raise CtxvcError("use either paths or --agent, not both")
    if agent_name:
        return [get_agent_path(repo_root, tool_root, agent_name)]
    if raw_paths:
        return [Path(p) for p in raw_paths]
    return [repo_root]


def print_diff(
    tool_root: Path,
    base_index: dict[str, dict[str, object]],
    target_index: dict[str, dict[str, object]],
    path_filter: str | None,
    prefix_filter: str | None,
) -> None:
    paths = sorted(set(base_index) | set(target_index))
    if prefix_filter:
        normalized = prefix_filter.rstrip("/") + "/"
        paths = [p for p in paths if p == prefix_filter or p.startswith(normalized)]
    if path_filter:
        paths = [p for p in paths if p == path_filter]
    if not paths:
        print("No matching files")
        return

    emitted = False
    for path in paths:
        left = base_index.get(path)
        right = target_index.get(path)
        if left and right and left["content_hash"] == right["content_hash"]:
            continue
        old_text = read_object(tool_root, left["content_hash"]) if left else ""
        new_text = resolve_entry_text(tool_root, right)
        rendered = list(
            difflib.unified_diff(
                old_text.splitlines(),
                (new_text or "").splitlines(),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="",
            )
        )
        if rendered:
            emitted = True
            print("\n".join(rendered))
    if not emitted:
        print("No differences found")
