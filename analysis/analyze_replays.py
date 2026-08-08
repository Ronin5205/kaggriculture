#!/usr/bin/env python3
"""Analyze Kaggriculture replay JSONs and extract stats / strategies.

Examples:
    python -m analysis.analyze_replays
    python -m analysis.analyze_replays --replays replays --out analysis_out --plots
    python -m analysis.analyze_replays --agent "Mohit Rao" --verbose
    python -m analysis.analyze_replays --episode 90503598 --plot-episode 90503598
    python -m analysis.analyze_replays --no-actions   # skip huge actions.csv
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .aggregate import aggregate_corpus
from .extract import extract_episode
from .load import discover_replays, load_replay
from .report import print_summary, write_outputs


def _analyze_one(
    path_str: str,
    sample_daily: bool,
    log_actions: bool,
    sample_hourly: bool,
) -> dict:
    path = Path(path_str)
    data = load_replay(path)
    return extract_episode(
        data,
        path,
        sample_daily=sample_daily,
        log_actions=log_actions,
        sample_hourly=sample_hourly,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--replays", type=Path, default=Path("replays"), help="Directory of replay JSON files")
    p.add_argument("--out", type=Path, default=Path("analysis_out"), help="Output directory")
    p.add_argument("--episode", type=str, default=None, help="Only analyze this episode id / filename stem")
    p.add_argument("--agent", type=str, default=None, help="Filter exported player/action rows to this agent")
    p.add_argument("--jobs", type=int, default=1, help="Parallel workers (1 = sequential)")
    p.add_argument("--no-daily", action="store_true", help="Skip daily board sampling / daily.csv")
    p.add_argument("--no-hourly", action="store_true", help="Skip per-turn hourly timeseries")
    p.add_argument("--no-actions", action="store_true", help="Skip per-action / market order logs")
    p.add_argument("--raw", action="store_true", help="Also write slim episodes_raw.json")
    p.add_argument("--plots", action="store_true", default=True, help="Generate matplotlib plots (default on)")
    p.add_argument("--no-plots", action="store_true", help="Skip matplotlib plots")
    p.add_argument("--plot-episode", type=str, default=None, help="Episode id for showcase plots")
    p.add_argument("--verbose", action="store_true", help="Print per-file progress")
    p.add_argument("--top", type=int, default=10, help="Rows to show in console summary")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = discover_replays(args.replays)

    if args.episode:
        needle = args.episode.replace(".json", "")
        paths = [p for p in paths if p.stem == needle or needle in p.stem]
        if not paths:
            print(f"No replay matching --episode {args.episode}", file=sys.stderr)
            return 1

    sample_daily = not args.no_daily
    sample_hourly = not args.no_hourly
    log_actions = not args.no_actions
    do_plots = args.plots and not args.no_plots

    print(f"Analyzing {len(paths)} replay(s) from {args.replays} ...")
    t0 = time.perf_counter()
    episodes: list[dict] = []

    if args.jobs <= 1:
        for i, path in enumerate(paths, 1):
            if args.verbose:
                print(f"  [{i}/{len(paths)}] {path.name}")
            try:
                episodes.append(
                    _analyze_one(str(path), sample_daily, log_actions, sample_hourly)
                )
            except Exception as exc:  # noqa: BLE001 — keep batch running
                print(f"  ERROR {path.name}: {exc}", file=sys.stderr)
    else:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            futs = {
                pool.submit(
                    _analyze_one, str(path), sample_daily, log_actions, sample_hourly
                ): path
                for path in paths
            }
            done = 0
            for fut in as_completed(futs):
                path = futs[fut]
                done += 1
                try:
                    episodes.append(fut.result())
                    if args.verbose:
                        print(f"  [{done}/{len(paths)}] {path.name}")
                except Exception as exc:  # noqa: BLE001
                    print(f"  ERROR {path.name}: {exc}", file=sys.stderr)

    if not episodes:
        print("No episodes analyzed.", file=sys.stderr)
        return 1

    corpus = aggregate_corpus(episodes)

    if args.agent:
        needle = args.agent.lower()

        def _match(row: dict) -> bool:
            return needle in str(row.get("agent", "")).lower()

        corpus["players"] = [r for r in corpus["players"] if _match(r)]
        corpus["daily"] = [r for r in corpus["daily"] if _match(r)]
        corpus["hourly"] = [r for r in corpus.get("hourly") or [] if _match(r)]
        corpus["actions"] = [r for r in corpus.get("actions") or [] if _match(r)]
        corpus["market_orders"] = [
            r for r in corpus.get("market_orders") or [] if _match(r)
        ]
        print(
            f"Filtered rows to agent matching {args.agent!r}: "
            f"{len(corpus['players'])} players, {len(corpus['actions'])} actions"
        )

    written = write_outputs(
        corpus,
        args.out,
        write_daily=sample_daily,
        write_hourly=sample_hourly,
        write_actions=log_actions,
        write_raw=args.raw,
    )

    plot_paths: list[Path] = []
    if do_plots:
        try:
            from .visualize import generate_plots

            plot_episode = args.plot_episode or args.episode
            plot_paths = generate_plots(
                corpus,
                args.out,
                episode_id=plot_episode,
                top_n=max(args.top, 12),
            )
            for path in plot_paths:
                written[f"plot:{path.name}"] = path
        except Exception as exc:  # noqa: BLE001
            print(f"Plot generation failed: {exc}", file=sys.stderr)

    elapsed = time.perf_counter() - t0
    print()
    print_summary(corpus, top_n=args.top)
    print()
    print(f"Wrote {len(written)} file(s) to {args.out} in {elapsed:.1f}s:")
    for name, path in written.items():
        print(f"  {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
