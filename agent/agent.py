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


def agent(obs):
    entry = _TURNS.get(obs.get("step", 0))
    if entry is None:
        return _DEFAULT

    player = obs["player"]
    hired_count = len(obs["farms"][player]["hands"])

    return {
        "farmer": _normalize_farmer(entry.get("farmer")),
        "hands": _normalize_hands(entry.get("hands"), hired_count),
        "market": entry.get("market") or [],
    }
