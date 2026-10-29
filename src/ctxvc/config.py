from __future__ import annotations

from pathlib import Path

from ctxvc.const import CONFIG_PATH
from ctxvc.errors import CtxvcError
from ctxvc.store import read_json, write_json


def read_config(tool_root: Path) -> dict[str, object]:
    config = read_json(tool_root / CONFIG_PATH)
    if "agents" not in config:
        config["agents"] = {}
        write_json(tool_root / CONFIG_PATH, config)
    return config


def validate_agent_name(name: str) -> None:
    if not name:
        raise CtxvcError("agent name cannot be empty")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    if any(ch not in allowed for ch in name):
        raise CtxvcError("agent name may only contain letters, numbers, '-', '_' ")


def resolve_within_repo(repo_root: Path, path: Path) -> Path:
    candidate = (
        (repo_root / path).resolve() if not path.is_absolute() else path.resolve()
    )
    try:
        candidate.relative_to(repo_root)
    except ValueError as exc:
        raise CtxvcError("path must be inside the repository") from exc
    return candidate


def get_agent_path(repo_root: Path, tool_root: Path, agent_name: str) -> Path:
    config = read_config(tool_root)
    agents = config.get("agents", {})
    if agent_name not in agents:
        raise CtxvcError(f"unknown agent: {agent_name}")
    return resolve_within_repo(repo_root, Path(str(agents[agent_name])))


def agent_prefix_path(repo_root: Path, tool_root: Path, agent_name: str) -> str:
    return get_agent_path(repo_root, tool_root, agent_name).relative_to(repo_root).as_posix()
