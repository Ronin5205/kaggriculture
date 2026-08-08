"""Load and normalize Kaggriculture replay JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def discover_replays(replays_dir: Path | str) -> list[Path]:
    root = Path(replays_dir)
    if not root.exists():
        raise FileNotFoundError(f"Replays directory not found: {root}")
    paths = sorted(root.glob("*.json"))
    if not paths:
        raise FileNotFoundError(f"No .json replays in {root}")
    return paths


def resolve_replay_path(replays_dir: Path | str, name: str | None) -> Path:
    paths = discover_replays(replays_dir)
    if name is None:
        return paths[-1]

    needle = name.replace(".json", "")
    matches = [p for p in paths if p.stem == needle or needle in p.stem]
    if not matches:
        available = ", ".join(p.name for p in paths)
        raise FileNotFoundError(
            f"No replay matching {name!r} in {replays_dir}\n"
            f"Available: {available}"
        )
    if len(matches) > 1:
        names = ", ".join(p.name for p in matches)
        raise ValueError(f"Replay name {name!r} is ambiguous: {names}")
    return matches[0]


def load_replay(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if "steps" not in data or "rewards" not in data:
        raise ValueError(f"Not a Kaggriculture replay JSON: {path}")
    return data


def agent_names(data: dict[str, Any]) -> list[str]:
    agents = data.get("info", {}).get("Agents") or []
    names = [a.get("Name") or f"player_{i}" for i, a in enumerate(agents)]
    while len(names) < 2:
        names.append(f"player_{len(names)}")
    return names[:2]


def episode_id(data: dict[str, Any], path: Path | None = None) -> str:
    info = data.get("info") or {}
    eid = info.get("EpisodeId")
    if eid is not None:
        return str(eid)
    if path is not None:
        return path.stem
    return str(data.get("id") or "unknown")


def turns_per_day(data: dict[str, Any]) -> int:
    cfg = data.get("configuration") or {}
    return int(cfg.get("turnsPerDay") or 24)
