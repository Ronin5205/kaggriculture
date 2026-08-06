"""Write analysis outputs and print a console summary."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = list(rows[0].keys())
    seen = set(fieldnames)
    for row in rows[1:]:
        for k in row:
            if k not in seen:
                fieldnames.append(k)
                seen.add(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            clean = {}
            for k, v in row.items():
                if isinstance(v, (list, dict)):
                    clean[k] = json.dumps(v, separators=(",", ":"))
                else:
                    clean[k] = v
            writer.writerow(clean)


def write_outputs(
    corpus: dict[str, Any],
    out_dir: Path | str,
    *,
    write_daily: bool = True,
    write_hourly: bool = True,
    write_actions: bool = True,
    write_raw: bool = False,
) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    paths = {
        "episodes": out / "episodes.csv",
        "players": out / "players.csv",
        "agents": out / "agents.csv",
        "strategies": out / "strategies.csv",
        "openings": out / "openings.csv",
        "op_counts": out / "op_counts.csv",
        "market_op_counts": out / "market_op_counts.csv",
    }
    _write_csv(paths["episodes"], corpus["episodes"])
    _write_csv(paths["players"], corpus["players"])
    _write_csv(paths["agents"], corpus["agents"])
    _write_csv(paths["strategies"], corpus["strategies"])
    _write_csv(paths["openings"], corpus["openings"])
    _write_csv(paths["op_counts"], corpus.get("op_counts") or [])
    _write_csv(paths["market_op_counts"], corpus.get("market_op_counts") or [])
    written.update(paths)

    if write_daily:
        daily_path = out / "daily.csv"
        _write_csv(daily_path, corpus["daily"])
        written["daily"] = daily_path

    if write_hourly:
        hourly_path = out / "hourly.csv"
        _write_csv(hourly_path, corpus.get("hourly") or [])
        written["hourly"] = hourly_path

    if write_actions:
        actions_path = out / "actions.csv"
        _write_csv(actions_path, corpus.get("actions") or [])
        written["actions"] = actions_path
        market_path = out / "market_orders.csv"
        _write_csv(market_path, corpus.get("market_orders") or [])
        written["market_orders"] = market_path

    summary = {
        "n_episodes": corpus["n_episodes"],
        "n_player_games": corpus["n_player_games"],
        "n_action_rows": len(corpus.get("actions") or []),
        "n_market_rows": len(corpus.get("market_orders") or []),
        "n_hourly_rows": len(corpus.get("hourly") or []),
        "top_agents": corpus["agents"][:10],
        "top_strategies": corpus["strategies"][:15],
        "top_ops": (corpus.get("op_counts") or [])[:15],
        "top_openings": [
            {
                "games": o["games"],
                "wins": o["wins"],
                "win_rate": o["win_rate"],
                "opening_fingerprint": o["opening_fingerprint"][:120]
                + ("..." if len(o["opening_fingerprint"]) > 120 else ""),
            }
            for o in corpus["openings"][:5]
        ],
    }
    summary_path = out / "corpus_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    written["summary"] = summary_path

    if write_raw:
        slim = []
        drop = {"daily", "money_by_day", "hourly", "action_log", "market_log", "ops_by_day"}
        for ep in corpus.get("raw_episodes") or []:
            copy = {k: v for k, v in ep.items() if k != "players"}
            players = []
            for p in ep.get("players") or []:
                sp = {k: v for k, v in p.items() if k not in drop}
                players.append(sp)
            copy["players"] = players
            slim.append(copy)
        raw_path = out / "episodes_raw.json"
        raw_path.write_text(json.dumps(slim, indent=2), encoding="utf-8")
        written["raw"] = raw_path

    return written


def print_summary(corpus: dict[str, Any], *, top_n: int = 10) -> None:
    print(f"Episodes: {corpus['n_episodes']}  player-games: {corpus['n_player_games']}")
    print(
        f"Action rows: {len(corpus.get('actions') or [])}  "
        f"market rows: {len(corpus.get('market_orders') or [])}  "
        f"hourly rows: {len(corpus.get('hourly') or [])}"
    )
    print()
    print("Top agents by avg final money:")
    print(f"  {'agent':28s} {'games':>5} {'wr':>6} {'avg$':>10} {'max$':>10} {'avg_mgn':>8}")
    for row in corpus["agents"][:top_n]:
        print(
            f"  {row['agent'][:28]:28s} {row['games']:5d} {row['win_rate']:6.3f} "
            f"{row['avg_money']:10.0f} {row['max_money']:10.0f} {row['avg_margin']:8.0f}"
        )

    print()
    print("Strategy tags (by avg money):")
    print(f"  {'strategy':24s} {'games':>5} {'wr':>6} {'avg$':>10}")
    for row in corpus["strategies"][:15]:
        print(
            f"  {row['strategy'][:24]:24s} {row['games']:5d} {row['win_rate']:6.3f} "
            f"{row['avg_money']:10.0f}"
        )

    print()
    print("Top unit actions:")
    for row in (corpus.get("op_counts") or [])[:10]:
        print(f"  {row['op']:20s} {row['count']:8d}")

    print()
    print("Opening book:")
    for i, row in enumerate(corpus["openings"][:5], 1):
        fp = row["opening_fingerprint"]
        short = fp if len(fp) <= 90 else fp[:87] + "..."
        print(
            f"  #{i} games={row['games']} wr={row['win_rate']:.3f}\n"
            f"      {short}"
        )

    print()
    print("Highest scoring episodes:")
    ranked = sorted(
        corpus["episodes"],
        key=lambda e: max(e["reward0"], e["reward1"]),
        reverse=True,
    )
    for e in ranked[:5]:
        print(
            f"  {e['episode_id']}: {e['agent0']}={e['reward0']:.0f} vs "
            f"{e['agent1']}={e['reward1']:.0f} (winner={e['winner']})"
        )
