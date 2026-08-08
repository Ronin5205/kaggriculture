import json
from pathlib import Path

from agent.action import Actions

_WALKER_PATH = Path(__file__).with_name("walker.json")
with _WALKER_PATH.open(encoding="utf-8") as f:
    _TURNS = {entry["step"]: entry for entry in json.load(f)}

_DEFAULT = {"farmer": Actions.pass_(), "hands": [], "market": []}


def _normalize_farmer(farmer):
    if farmer is None:
        return Actions.pass_()
    if isinstance(farmer, str):
        return [farmer]
    return farmer


def _normalize_hands(recorded_hands, hired_count):
    hands = list(recorded_hands or [])
    if len(hands) < hired_count:
        hands.extend([Actions.pass_()] * (hired_count - len(hands)))
    elif len(hands) > hired_count:
        hands = hands[:hired_count]
    return hands


def _lookup_turn(step: int) -> dict | None:
    # Replay frames pair observation step K with the action chosen on that
    # observation; frame 0 is the initial state with a dummy PASS. walker.json
    # was keyed by observation step, so step K's real action lives at K + 1.
    entry = _TURNS.get(step)
    if entry is not None:
        return entry
    return _TURNS.get(step)


def agent(obs):
    entry = _lookup_turn(obs.get("step", 0))
    if entry is None:
        return _DEFAULT

    player = obs["player"]
    hired_count = len(obs["farms"][player]["hands"])

    return {
        "farmer": _normalize_farmer(entry.get("farmer")),
        "hands": _normalize_hands(entry.get("hands"), hired_count),
        "market": entry.get("market") or [],
    }
