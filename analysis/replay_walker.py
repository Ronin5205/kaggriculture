"""Extract player 0 actions from a Kaggriculture replay into agent/walker.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .load import load_replay, resolve_replay_path

PLAYER = 0
MAX_DAY = 30  # inclusive upper bound on day index (season days are 0..29)

ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / "agent"
PRETTY_REPLAY_DIR = ROOT / "pretty_replay"
OUT_PATH = AGENT_DIR / "walker.json"


def walk(replay: dict, player: int = PLAYER) -> list[dict]:
    steps = replay["steps"]
    turns = []

    # Frame 0 is the initial observation (dummy PASS). Frame i>0 stores the
    # action chosen when the agent saw the observation in frame i - 1.
    for i in range(1, len(steps)):
        entry = steps[i][player]
        obs = (steps[i - 1][player].get("observation") or {})
        day = obs.get("day")
        if day is None or day >= MAX_DAY:
            continue

        action = entry.get("action") or {}
        turns.append(
            {
                "step": obs.get("step", i - 1),
                "day": day,
                "hour": obs.get("hour"),
                "farmer": action.get("farmer", ["PASS"]),
                "hands": action.get("hands", []),
                "market": action.get("market", []),
            }
        )

    return turns


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Extract player 0 actions from a prettified replay into agent/walker.json."
    )
    p.add_argument(
        "replay",
        nargs="?",
        default=None,
        help="Replay filename or stem in pretty_replay/ (default: latest file)",
    )
    p.add_argument(
        "--pretty-replay",
        type=Path,
        default=PRETTY_REPLAY_DIR,
        help=f"Prettified replay directory (default: {PRETTY_REPLAY_DIR})",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=OUT_PATH,
        help=f"Output path (default: {OUT_PATH})",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        src = resolve_replay_path(args.pretty_replay, args.replay)
        replay = load_replay(src)
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    turns = walk(replay)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        json.dump(turns, f, indent=2)
    print(f"Read {src}")
    print(f"Wrote {len(turns)} turns -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
