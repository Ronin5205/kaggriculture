"""Aggregate extracted episodes into corpus-level tables."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def _flat_player_row(episode: dict[str, Any], player: dict[str, Any]) -> dict[str, Any]:
    buy_seed = player.get("buy_seed") or {}
    buy_animal = player.get("buy_animal") or {}
    plant = player.get("plant_counts") or {}
    sell_qty = player.get("sell_qty") or {}
    sell_rev = player.get("sell_revenue") or {}
    unlock = player.get("unlock_day") or {}
    op_mix = player.get("op_mix") or {}

    return {
        "episode_id": episode["episode_id"],
        "seed": episode.get("seed"),
        "player": player["player"],
        "agent": player["agent"],
        "opponent": player["opponent"],
        "result": player["result"],
        "final_money": player["final_money"],
        "opponent_money": player["opponent_money"],
        "margin": player["margin"],
        "opening_fingerprint": player.get("opening_fingerprint"),
        "open_hires": player.get("open_hires"),
        "open_animals": player.get("open_animals"),
        "open_melon_seeds": player.get("open_melon_seeds"),
        "open_wheat_seeds": player.get("open_wheat_seeds"),
        "total_hires": player.get("total_hires"),
        "median_daily_hires": player.get("median_daily_hires"),
        "max_daily_hires": player.get("max_daily_hires"),
        "peak_hands": player.get("peak_hands"),
        "buy_land": player.get("buy_land"),
        "second_quadrant_day": player.get("second_quadrant_day"),
        "n_quadrants_final": player.get("n_quadrants_final"),
        "unlock_NE": unlock.get("NE"),
        "unlock_SW": unlock.get("SW"),
        "unlock_SE": unlock.get("SE"),
        "plants_wheat": plant.get("WHEAT", 0),
        "plants_carrot": plant.get("CARROT", 0),
        "plants_tomato": plant.get("TOMATO", 0),
        "plants_strawberry": plant.get("STRAWBERRY", 0),
        "plants_melon": plant.get("MELON", 0),
        "buy_seed_wheat": buy_seed.get("WHEAT", 0),
        "buy_seed_melon": buy_seed.get("MELON", 0),
        "buy_seed_strawberry": buy_seed.get("STRAWBERRY", 0),
        "buy_seed_tomato": buy_seed.get("TOMATO", 0),
        "buy_seed_carrot": buy_seed.get("CARROT", 0),
        "buy_cow": buy_animal.get("COW", 0),
        "buy_sheep": buy_animal.get("SHEEP", 0),
        "buy_goose": buy_animal.get("GOOSE", 0),
        "bought_wheat": player.get("bought_wheat"),
        "wheat_self_ratio": player.get("wheat_self_ratio"),
        "sell_wheat": sell_qty.get("WHEAT", 0),
        "sell_melon": sell_qty.get("MELON", 0),
        "sell_strawberry": sell_qty.get("STRAWBERRY", 0),
        "sell_milk": sell_qty.get("MILK", 0),
        "sell_wool": sell_qty.get("WOOL", 0),
        "sell_egg": sell_qty.get("EGG", 0),
        "sell_fertilizer": sell_qty.get("FERTILIZER", 0),
        "rev_wheat": sell_rev.get("WHEAT", 0),
        "rev_melon": sell_rev.get("MELON", 0),
        "rev_strawberry": sell_rev.get("STRAWBERRY", 0),
        "rev_milk": sell_rev.get("MILK", 0),
        "rev_wool": sell_rev.get("WOOL", 0),
        "rev_egg": sell_rev.get("EGG", 0),
        "rev_fertilizer": sell_rev.get("FERTILIZER", 0),
        "total_sell_revenue": player.get("total_sell_revenue"),
        "fertilize": player.get("fertilize"),
        "care": player.get("care"),
        "collect_fertilizer": player.get("collect_fertilizer"),
        "build_coop": player.get("build_coop"),
        "build_pasture": player.get("build_pasture"),
        "peak_plants": player.get("peak_plants"),
        "peak_animals": player.get("peak_animals"),
        "peak_weeds": player.get("peak_weeds"),
        "pct_move": player.get("pct_move"),
        "pct_field": player.get("pct_field"),
        "pct_pass": player.get("pct_pass"),
        "total_unit_actions": player.get("total_unit_actions"),
        "op_water": op_mix.get("WATER", 0),
        "op_feed": op_mix.get("FEED", 0),
        "op_care": op_mix.get("CARE", 0),
        "op_harvest": op_mix.get("HARVEST", 0),
        "op_plant": op_mix.get("PLANT", 0),
        "op_pass": op_mix.get("PASS", 0),
        "strategies": ",".join(player.get("strategies") or []),
        "first_sell_melon": (player.get("first_sell_day") or {}).get("MELON"),
        "first_sell_milk": (player.get("first_sell_day") or {}).get("MILK"),
        "first_sell_wool": (player.get("first_sell_day") or {}).get("WOOL"),
        "first_sell_strawberry": (player.get("first_sell_day") or {}).get("STRAWBERRY"),
        "n_action_rows": len(player.get("action_log") or []),
        "n_market_rows": len(player.get("market_log") or []),
    }


def aggregate_corpus(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    episode_rows = []
    player_rows = []
    daily_rows = []
    hourly_rows = []
    action_rows = []
    market_rows = []

    agent_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "games": 0,
            "wins": 0,
            "losses": 0,
            "ties": 0,
            "money_sum": 0.0,
            "money_max": 0.0,
            "money_min": float("inf"),
            "margins": [],
            "strategies": Counter(),
            "openings": Counter(),
        }
    )
    strategy_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"games": 0, "wins": 0, "money_sum": 0.0}
    )
    opening_stats: Counter = Counter()
    opening_wins: Counter = Counter()
    corpus_op_counts: Counter = Counter()
    corpus_market_counts: Counter = Counter()

    for ep in episodes:
        episode_rows.append({
            "episode_id": ep["episode_id"],
            "path": ep.get("path"),
            "seed": ep.get("seed"),
            "agent0": ep["agents"][0],
            "agent1": ep["agents"][1],
            "reward0": ep["rewards"][0],
            "reward1": ep["rewards"][1],
            "winner": ep["winner"],
            "margin": ep["margin"],
            "n_steps": ep["n_steps"],
        })

        for player in ep["players"]:
            row = _flat_player_row(ep, player)
            player_rows.append(row)

            agent = player["agent"]
            st = agent_stats[agent]
            st["games"] += 1
            st["money_sum"] += player["final_money"]
            st["money_max"] = max(st["money_max"], player["final_money"])
            st["money_min"] = min(st["money_min"], player["final_money"])
            st["margins"].append(player["margin"])
            if player["result"] == "win":
                st["wins"] += 1
            elif player["result"] == "loss":
                st["losses"] += 1
            else:
                st["ties"] += 1
            for tag in player.get("strategies") or []:
                st["strategies"][tag] += 1
            fp = player.get("opening_fingerprint") or ""
            if fp:
                st["openings"][fp] += 1
                opening_stats[fp] += 1
                if player["result"] == "win":
                    opening_wins[fp] += 1

            for tag in player.get("strategies") or []:
                ss = strategy_stats[tag]
                ss["games"] += 1
                ss["money_sum"] += player["final_money"]
                if player["result"] == "win":
                    ss["wins"] += 1

            for op, n in (player.get("op_counts") or {}).items():
                corpus_op_counts[op] += int(n)
            for op, n in (player.get("market_op_counts") or {}).items():
                corpus_market_counts[op] += int(n)

            for day_row in player.get("daily") or []:
                daily_rows.append({
                    "episode_id": ep["episode_id"],
                    "player": player["player"],
                    "agent": player["agent"],
                    "result": player["result"],
                    **{k: v for k, v in day_row.items()},
                })

            for hour_row in player.get("hourly") or []:
                hourly_rows.append({
                    "episode_id": ep["episode_id"],
                    "player": player["player"],
                    "agent": player["agent"],
                    "result": player["result"],
                    **{k: v for k, v in hour_row.items()},
                })

            for act in player.get("action_log") or []:
                action_rows.append({
                    "episode_id": ep["episode_id"],
                    "player": player["player"],
                    "agent": player["agent"],
                    **act,
                })

            for mkt in player.get("market_log") or []:
                market_rows.append({
                    "episode_id": ep["episode_id"],
                    "player": player["player"],
                    "agent": player["agent"],
                    **mkt,
                })

    agents_table = []
    for agent, st in agent_stats.items():
        games = st["games"] or 1
        agents_table.append({
            "agent": agent,
            "games": st["games"],
            "wins": st["wins"],
            "losses": st["losses"],
            "ties": st["ties"],
            "win_rate": round(st["wins"] / games, 3),
            "avg_money": round(st["money_sum"] / games, 1),
            "max_money": st["money_max"],
            "min_money": st["money_min"] if st["money_min"] != float("inf") else 0,
            "avg_margin": round(sum(st["margins"]) / games, 1),
            "top_strategies": ",".join(
                f"{k}:{v}" for k, v in st["strategies"].most_common(5)
            ),
            "top_opening": st["openings"].most_common(1)[0][0] if st["openings"] else "",
        })
    agents_table.sort(key=lambda r: (-r["avg_money"], -r["win_rate"], -r["games"]))

    strategies_table = []
    for tag, ss in strategy_stats.items():
        games = ss["games"] or 1
        strategies_table.append({
            "strategy": tag,
            "games": ss["games"],
            "wins": ss["wins"],
            "win_rate": round(ss["wins"] / games, 3),
            "avg_money": round(ss["money_sum"] / games, 1),
        })
    strategies_table.sort(key=lambda r: (-r["avg_money"], -r["games"]))

    openings_table = []
    for fp, n in opening_stats.most_common():
        openings_table.append({
            "opening_fingerprint": fp,
            "games": n,
            "wins": opening_wins[fp],
            "win_rate": round(opening_wins[fp] / n, 3) if n else 0,
        })

    op_table = [
        {"op": op, "count": n}
        for op, n in corpus_op_counts.most_common()
    ]
    market_op_table = [
        {"op": op, "count": n}
        for op, n in corpus_market_counts.most_common()
    ]

    return {
        "n_episodes": len(episodes),
        "n_player_games": len(player_rows),
        "episodes": episode_rows,
        "players": player_rows,
        "daily": daily_rows,
        "hourly": hourly_rows,
        "actions": action_rows,
        "market_orders": market_rows,
        "agents": agents_table,
        "strategies": strategies_table,
        "openings": openings_table,
        "op_counts": op_table,
        "market_op_counts": market_op_table,
        "raw_episodes": episodes,
    }
