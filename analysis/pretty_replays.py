"""Pretty-print a replay JSON file for easier inspection."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .load import resolve_replay_path

ROOT = Path(__file__).resolve().parent.parent
REPLAYS_DIR = ROOT / "replays"
OUTPUT_DIR = ROOT / "pretty_replay"


def prettify(src: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"{src.stem}_pretty.json"
    with src.open(encoding="utf-8") as f:
        data = json.load(f)
    with dst.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    return dst


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pretty-print a Kaggriculture replay JSON for inspection."
    )
    p.add_argument(
        "replay",
        nargs="?",
        default=None,
        help="Replay filename or stem in replays/ (default: latest file)",
    )
    p.add_argument(
        "--replays",
        type=Path,
        default=REPLAYS_DIR,
        help=f"Source replay directory (default: {REPLAYS_DIR})",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=OUTPUT_DIR,
        help=f"Output directory (default: {OUTPUT_DIR})",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        src = resolve_replay_path(args.replays, args.replay)
        dst = prettify(src, args.out)
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"Read {src}")
    print(f"Wrote {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
