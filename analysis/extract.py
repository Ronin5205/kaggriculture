"""Extract per-player stats, action logs, and timeseries from one replay."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .load import agent_names, episode_id, turns_per_day
from .strategies import label_strategies


CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
ANIMALS = ("GOOSE", "COW", "SHEEP")
PRODUCTS = (
    "WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
    "EGG", "MILK", "WOOL", "FERTILIZER",
)
MOVE_OPS = {"NORTH", "SOUTH", "EAST", "WEST"}
FIELD_OPS = {
    "WATER", "HARVEST", "PLANT", "FERTILIZE", "DIG",
    "FEED", "CARE", "COLLECT_FERTILIZER",
    "BUILD_COOP", "BUILD_PASTURE", "PLACE",
}
KEY_UNIT_OPS = (
    "PASS", "NORTH", "SOUTH", "EAST", "WEST",
    "WATER", "HARVEST", "PLANT", "FERTILIZE", "DIG",
    "FEED", "CARE", "COLLECT_FERTILIZER",
    "PICKUP", "DROP", "PLACE",
    "BUILD_COOP", "BUILD_PASTURE",
)


def _op_name(op: Any) -> str | None:
    if isinstance(op, list) and op:
        return str(op[0])
    if isinstance(op, str):
        return op
    return None


def _op_args(op: Any) -> list[Any]:
    if isinstance(op, list) and len(op) > 1:
        return list(op[1:])
    return []


def _fmt_args(args: list[Any], n: int = 3) -> list[Any]:
    out = list(args[:n])
    while len(out) < n:
        out.append("")
    return out


def _unit_ops(action: dict[str, Any]) -> list[tuple[str, Any]]:
    """Return (unit_id, op) pairs for farmer + hands."""
    ops: list[tuple[str, Any]] = []
    farmer = action.get("farmer")
    if farmer is not None:
        ops.append(("farmer", farmer))
    for i, hand in enumerate(action.get("hands") or []):
        ops.append((f"hand{i}", hand))
    return ops


def _unit_pos(farm: dict[str, Any], unit_id: str) -> tuple[Any, Any]:
    if unit_id == "farmer":
        pos = farm.get("farmer") or [None, None]
        return (pos[0] if len(pos) > 0 else None, pos[1] if len(pos) > 1 else None)
    if unit_id.startswith("hand"):
        try:
            idx = int(unit_id[4:])
        except ValueError:
            return (None, None)
        hands = farm.get("hands") or []
        if 0 <= idx < len(hands):
            pos = hands[idx] or [None, None]
            return (pos[0] if len(pos) > 0 else None, pos[1] if len(pos) > 1 else None)
    return (None, None)


def _scan_board(tiles: list[list[Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    crop_counts: Counter[str] = Counter()
    animal_counts: Counter[str] = Counter()
    for row in tiles or []:
        for tile in row:
            if tile is None or tile == "LOCKED":
                continue
            if not isinstance(tile, dict):
                continue
            kind = tile.get("kind")
            if kind == "PLANT":
                counts["plants"] += 1
                crop = tile.get("crop")
                if crop:
                    crop_counts[str(crop)] += 1
            elif kind == "WEED":
                counts["weeds"] += 1
            elif kind in ("COOP", "PASTURE"):
                counts["structures"] += 1
                animal = tile.get("animal")
                if animal:
                    counts["animals"] += 1
                    animal_counts[str(animal)] += 1
                else:
                    counts["empty_structures"] += 1
    out = dict(counts)
    for crop, n in crop_counts.items():
        out[f"crop_{crop}"] = n
    for animal, n in animal_counts.items():
        out[f"animal_{animal}"] = n
    return out


def _empty_player_accum() -> dict[str, Any]:
    return {
        "op_counts": Counter(),
        "market_op_counts": Counter(),
        "plant_counts": Counter(),
        "buy_seed": Counter(),
        "buy_animal": Counter(),
        "buy_product": Counter(),
        "sell_qty": Counter(),
        "sell_revenue": Counter(),
        "sell_price_sum": Counter(),
        "sell_price_n": Counter(),
        "hires": 0,
        "buy_land": 0,
        "fertilize": 0,
        "care": 0,
        "collect_fertilizer": 0,
        "build_coop": 0,
        "build_pasture": 0,
        "place_animal": Counter(),
        "hires_by_day": Counter(),
        "ops_by_day": defaultdict_counter(),
        "sell_rev_by_day": defaultdict_float(),
        "sell_qty_by_day": defaultdict_counter(),
        "first_sell_day": {},
        "first_plant_day": {},
        "first_animal_day": {},
        "unlock_day": {"NW": 0},
        "opening_market": [],
        "daily": [],
        "hourly": [],
        "action_log": [],
        "market_log": [],
        "peak_plants": 0,
        "peak_animals": 0,
        "peak_weeds": 0,
        "peak_hands": 0,
        "money_by_day": [],
        "cum_sell_revenue": 0.0,
    }


def defaultdict_counter() -> dict[Any, Counter]:
    return {}


def defaultdict_float() -> dict[Any, float]:
    return {}


def _day_counter(store: dict[Any, Counter], day: int) -> Counter:
    if day not in store:
        store[day] = Counter()
    return store[day]


def extract_player(
    data: dict[str, Any],
    player: int,
    *,
    sample_daily: bool = True,
    log_actions: bool = True,
    sample_hourly: bool = True,
) -> dict[str, Any]:
    steps = data["steps"]
    tpd = turns_per_day(data)
    names = agent_names(data)
    rewards = data.get("rewards") or [0, 0]
    statuses = data.get("statuses") or ["", ""]

    acc = _empty_player_accum()
    prev_unlocked = None
    prev_money = None
    prev_step_money = None

    for t, step in enumerate(steps):
        if player >= len(step):
            continue
        entry = step[player]
        action = entry.get("action") or {}
        if not isinstance(action, dict):
            action = {}
        obs = entry.get("observation") or {}
        day = int(obs.get("day") if obs.get("day") is not None else t // tpd)
        hour = int(obs.get("hour") if obs.get("hour") is not None else t % tpd)

        farms = obs.get("farms") or []
        farm = farms[player] if player < len(farms) else {}
        money = float(farm.get("money") or 0)
        hands = farm.get("hands") or []
        unlocked = list(farm.get("unlocked_quadrants") or [])
        private = obs.get("private") or {}
        market_state = obs.get("market") or {}
        prices = market_state.get("prices") or {}
        inventory = market_state.get("inventory") or {}

        money_delta = 0.0 if prev_step_money is None else money - prev_step_money
        prev_step_money = money

        acc["peak_hands"] = max(acc["peak_hands"], len(hands))

        if prev_unlocked is None:
            for q in unlocked:
                acc["unlock_day"].setdefault(q, day)
        else:
            for q in unlocked:
                if q not in prev_unlocked:
                    acc["unlock_day"].setdefault(q, day)
        prev_unlocked = set(unlocked)

        if not acc["opening_market"]:
            market_orders = action.get("market") or []
            if market_orders:
                acc["opening_market"] = [list(m) for m in market_orders]

        hour_ops: Counter[str] = Counter()
        hour_sell_rev = 0.0
        hour_sell_qty = 0
        hour_market_orders = 0

        # Unit actions.
        for unit_id, op in _unit_ops(action):
            name = _op_name(op)
            if not name:
                continue
            args = _op_args(op)
            acc["op_counts"][name] += 1
            hour_ops[name] += 1
            _day_counter(acc["ops_by_day"], day)[name] += 1

            if name == "PLANT" and args:
                crop = str(args[0])
                acc["plant_counts"][crop] += 1
                acc["first_plant_day"].setdefault(crop, day)
            elif name == "FERTILIZE":
                acc["fertilize"] += 1
            elif name == "CARE":
                acc["care"] += 1
            elif name == "COLLECT_FERTILIZER":
                acc["collect_fertilizer"] += 1
            elif name == "BUILD_COOP":
                acc["build_coop"] += 1
            elif name == "BUILD_PASTURE":
                acc["build_pasture"] += 1
            elif name == "PLACE" and args:
                item = str(args[0])
                if item in ANIMALS:
                    acc["place_animal"][item] += 1
                    acc["first_animal_day"].setdefault(item, day)

            if log_actions:
                x, y = _unit_pos(farm, unit_id)
                a0, a1, a2 = _fmt_args(args)
                acc["action_log"].append({
                    "step": t,
                    "day": day,
                    "hour": hour,
                    "unit": unit_id,
                    "op": name,
                    "arg0": a0,
                    "arg1": a1,
                    "arg2": a2,
                    "x": x,
                    "y": y,
                    "money": money,
                    "n_hands": len(hands),
                })

        # Market orders.
        for order_i, order in enumerate(action.get("market") or []):
            if not isinstance(order, list) or not order:
                continue
            op = str(order[0])
            acc["market_op_counts"][op] += 1
            hour_market_orders += 1
            item = str(order[1]) if len(order) > 1 else ""
            qty = int(order[2]) if len(order) > 2 else (1 if op != "HIRE" and op != "BUY_LAND" else 1)
            price = float(prices.get(item) or 0) if item else 0.0

            if op == "HIRE":
                acc["hires"] += 1
                acc["hires_by_day"][day] += 1
                qty = 1
                item = ""
                price = 0.0
            elif op == "BUY_LAND":
                acc["buy_land"] += 1
                qty = 1
                item = ""
                price = 0.0
            elif op == "BUY_SEED" and item:
                acc["buy_seed"][item] += qty
            elif op == "BUY_ANIMAL" and item:
                acc["buy_animal"][item] += qty
                acc["first_animal_day"].setdefault(item, day)
            elif op == "BUY_PRODUCT" and item:
                acc["buy_product"][item] += qty
            elif op == "SELL" and item:
                acc["sell_qty"][item] += qty
                rev = qty * price
                acc["sell_revenue"][item] += rev
                acc["cum_sell_revenue"] += rev
                hour_sell_rev += rev
                hour_sell_qty += qty
                if day not in acc["sell_rev_by_day"]:
                    acc["sell_rev_by_day"][day] = 0.0
                acc["sell_rev_by_day"][day] += rev
                _day_counter(acc["sell_qty_by_day"], day)[item] += qty
                if price > 0:
                    acc["sell_price_sum"][item] += price
                    acc["sell_price_n"][item] += 1
                acc["first_sell_day"].setdefault(item, day)

            if log_actions:
                acc["market_log"].append({
                    "step": t,
                    "day": day,
                    "hour": hour,
                    "order_i": order_i,
                    "op": op,
                    "item": item,
                    "qty": qty,
                    "price": price,
                    "revenue": round(qty * price, 2) if op == "SELL" else 0.0,
                    "money": money,
                    "market_inv": inventory.get(item) if item else None,
                })

        # Hourly snapshot (every turn) — compact trend series without unit rows.
        if sample_hourly:
            move_n = sum(hour_ops[o] for o in MOVE_OPS)
            field_n = sum(hour_ops[o] for o in FIELD_OPS)
            row_h = {
                "step": t,
                "day": day,
                "hour": hour,
                "money": money,
                "money_delta": round(money_delta, 2),
                "hands": len(hands),
                "hires_today": int(farm.get("hires_today") or 0),
                "n_unlocked": len(unlocked),
                "cum_sell_revenue": round(acc["cum_sell_revenue"], 2),
                "sell_rev": round(hour_sell_rev, 2),
                "sell_qty": hour_sell_qty,
                "market_orders": hour_market_orders,
                "n_units": 1 + len(hands),
                "move": move_n,
                "field": field_n,
                "pass": hour_ops.get("PASS", 0),
                "water": hour_ops.get("WATER", 0),
                "feed": hour_ops.get("FEED", 0),
                "care": hour_ops.get("CARE", 0),
                "harvest": hour_ops.get("HARVEST", 0),
                "plant": hour_ops.get("PLANT", 0),
                "fertilize": hour_ops.get("FERTILIZE", 0),
                "pickup": hour_ops.get("PICKUP", 0),
                "drop": hour_ops.get("DROP", 0),
                "price_wheat": prices.get("WHEAT"),
                "price_melon": prices.get("MELON"),
                "price_strawberry": prices.get("STRAWBERRY"),
                "price_milk": prices.get("MILK"),
                "price_wool": prices.get("WOOL"),
                "price_egg": prices.get("EGG"),
                "price_fertilizer": prices.get("FERTILIZER"),
            }
            # Board scan hourly is expensive; sample every 6 turns + day boundaries.
            if hour % 6 == 0 or hour == 0 or t == len(steps) - 1:
                board = _scan_board(farm.get("tiles") or [])
                row_h["plants"] = board.get("plants", 0)
                row_h["animals"] = board.get("animals", 0)
                row_h["weeds"] = board.get("weeds", 0)
                for crop in CROPS:
                    row_h[f"crop_{crop}"] = board.get(f"crop_{crop}", 0)
                for animal in ANIMALS:
                    row_h[f"animal_{animal}"] = board.get(f"animal_{animal}", 0)
                acc["peak_plants"] = max(acc["peak_plants"], row_h["plants"])
                acc["peak_animals"] = max(acc["peak_animals"], row_h["animals"])
                acc["peak_weeds"] = max(acc["peak_weeds"], row_h["weeds"])
            acc["hourly"].append(row_h)

        # Daily snapshot at hour 0 (and final step).
        is_day_start = hour == 0
        is_last = t == len(steps) - 1
        if sample_daily and (is_day_start or is_last):
            tiles = farm.get("tiles") or []
            board = _scan_board(tiles)
            plants = board.get("plants", 0)
            animals = board.get("animals", 0)
            weeds = board.get("weeds", 0)
            acc["peak_plants"] = max(acc["peak_plants"], plants)
            acc["peak_animals"] = max(acc["peak_animals"], animals)
            acc["peak_weeds"] = max(acc["peak_weeds"], weeds)

            delta = 0.0 if prev_money is None else money - prev_money
            day_ops = acc["ops_by_day"].get(day - 1, Counter()) if day > 0 else Counter()
            row = {
                "day": day,
                "hour": hour,
                "step": t,
                "money": money,
                "delta_money": delta if is_day_start and day > 0 else (
                    0.0 if is_day_start else money - (prev_money or money)
                ),
                "hands": len(hands),
                "hires_today": int(farm.get("hires_today") or 0),
                "unlocked": ",".join(sorted(unlocked)),
                "n_unlocked": len(unlocked),
                "plants": plants,
                "animals": animals,
                "weeds": weeds,
                "structures": board.get("structures", 0),
                "seeds_wheat": int((private.get("seeds") or {}).get("WHEAT") or 0),
                "shed_wheat": int((private.get("shed") or {}).get("WHEAT") or 0),
                "town_shops": len((obs.get("town") or {}).get("unlocked_shops") or []),
                "cum_sell_revenue": round(acc["cum_sell_revenue"], 2),
                "sell_rev_prev_day": round(acc["sell_rev_by_day"].get(day - 1, 0.0), 2) if day > 0 else 0.0,
                "ops_water_prev": day_ops.get("WATER", 0) if day > 0 else 0,
                "ops_feed_prev": day_ops.get("FEED", 0) if day > 0 else 0,
                "ops_care_prev": day_ops.get("CARE", 0) if day > 0 else 0,
                "ops_harvest_prev": day_ops.get("HARVEST", 0) if day > 0 else 0,
                "ops_plant_prev": day_ops.get("PLANT", 0) if day > 0 else 0,
                "ops_move_prev": sum(day_ops[o] for o in MOVE_OPS) if day > 0 else 0,
                "ops_pass_prev": day_ops.get("PASS", 0) if day > 0 else 0,
            }
            for crop in CROPS:
                row[f"crop_{crop}"] = board.get(f"crop_{crop}", 0)
            for animal in ANIMALS:
                row[f"animal_{animal}"] = board.get(f"animal_{animal}", 0)
            for prod in ("WHEAT", "MELON", "STRAWBERRY", "MILK", "WOOL", "EGG", "FERTILIZER"):
                row[f"sell_qty_prev_{prod}"] = (
                    acc["sell_qty_by_day"].get(day - 1, Counter()).get(prod, 0) if day > 0 else 0
                )

            if is_day_start:
                acc["daily"].append(row)
                acc["money_by_day"].append(money)
                prev_money = money
            elif is_last:
                if not acc["daily"] or acc["daily"][-1]["step"] != t:
                    acc["daily"].append(row)

    final_money = float(rewards[player]) if player < len(rewards) else 0.0
    opp = 1 - player
    opp_money = float(rewards[opp]) if opp < len(rewards) else 0.0
    if final_money > opp_money:
        result = "win"
    elif final_money < opp_money:
        result = "loss"
    else:
        result = "tie"

    total_ops = sum(acc["op_counts"].values()) or 1
    move_n = sum(acc["op_counts"][op] for op in MOVE_OPS)
    field_n = sum(acc["op_counts"][op] for op in FIELD_OPS)
    pass_n = acc["op_counts"].get("PASS", 0)

    avg_sell_price = {}
    for item, n in acc["sell_price_n"].items():
        if n:
            avg_sell_price[item] = acc["sell_price_sum"][item] / n

    hires_by_day = acc["hires_by_day"]
    hire_days = sorted(hires_by_day)
    median_hires = 0
    if hire_days:
        vals = [hires_by_day[d] for d in range(max(hire_days) + 1)]
        vals_sorted = sorted(vals)
        mid = len(vals_sorted) // 2
        median_hires = (
            vals_sorted[mid]
            if len(vals_sorted) % 2
            else (vals_sorted[mid - 1] + vals_sorted[mid]) / 2
        )

    early_melon_seeds = acc["buy_seed"].get("MELON", 0)
    day0_animals = sum(acc["buy_animal"].values())
    opening = acc["opening_market"]
    open_animals = 0
    open_melon = 0
    open_wheat_seed = 0
    open_hires = 0
    for order in opening:
        if not order:
            continue
        op = order[0]
        if op == "HIRE":
            open_hires += 1
        elif op == "BUY_ANIMAL" and len(order) >= 2:
            open_animals += int(order[2]) if len(order) > 2 else 1
        elif op == "BUY_SEED" and len(order) >= 2:
            n = int(order[2]) if len(order) > 2 else 1
            if order[1] == "MELON":
                open_melon += n
            elif order[1] == "WHEAT":
                open_wheat_seed += n

    grown_wheat_proxy = acc["plant_counts"].get("WHEAT", 0)
    bought_wheat = acc["buy_product"].get("WHEAT", 0) + acc["buy_seed"].get("WHEAT", 0)

    # Action-mix breakdown for charts / advanced stats.
    op_mix = {op: int(acc["op_counts"].get(op, 0)) for op in KEY_UNIT_OPS}
    op_mix["OTHER"] = int(total_ops - sum(op_mix.values()))

    summary = {
        "player": player,
        "agent": names[player],
        "opponent": names[opp],
        "final_money": final_money,
        "opponent_money": opp_money,
        "margin": final_money - opp_money,
        "result": result,
        "status": statuses[player] if player < len(statuses) else "",
        "opening_market": opening,
        "opening_fingerprint": _fingerprint(opening),
        "open_hires": open_hires,
        "open_animals": open_animals,
        "open_melon_seeds": open_melon,
        "open_wheat_seeds": open_wheat_seed,
        "total_hires": acc["hires"],
        "median_daily_hires": median_hires,
        "max_daily_hires": max(hires_by_day.values()) if hires_by_day else 0,
        "peak_hands": acc["peak_hands"],
        "buy_land": acc["buy_land"],
        "unlock_day": dict(acc["unlock_day"]),
        "second_quadrant_day": _second_quadrant_day(acc["unlock_day"]),
        "n_quadrants_final": len(acc["unlock_day"]),
        "buy_seed": dict(acc["buy_seed"]),
        "buy_animal": dict(acc["buy_animal"]),
        "buy_product": dict(acc["buy_product"]),
        "plant_counts": dict(acc["plant_counts"]),
        "place_animal": dict(acc["place_animal"]),
        "sell_qty": dict(acc["sell_qty"]),
        "sell_revenue": {k: round(v, 2) for k, v in acc["sell_revenue"].items()},
        "avg_sell_price": {k: round(v, 2) for k, v in avg_sell_price.items()},
        "first_sell_day": dict(acc["first_sell_day"]),
        "first_plant_day": dict(acc["first_plant_day"]),
        "first_animal_day": dict(acc["first_animal_day"]),
        "total_sell_revenue": round(sum(acc["sell_revenue"].values()), 2),
        "fertilize": acc["fertilize"],
        "care": acc["care"],
        "collect_fertilizer": acc["collect_fertilizer"],
        "build_coop": acc["build_coop"],
        "build_pasture": acc["build_pasture"],
        "peak_plants": acc["peak_plants"],
        "peak_animals": acc["peak_animals"],
        "peak_weeds": acc["peak_weeds"],
        "op_counts": dict(acc["op_counts"]),
        "op_mix": op_mix,
        "market_op_counts": dict(acc["market_op_counts"]),
        "pct_move": round(100.0 * move_n / total_ops, 2),
        "pct_field": round(100.0 * field_n / total_ops, 2),
        "pct_pass": round(100.0 * pass_n / total_ops, 2),
        "total_unit_actions": int(total_ops),
        "grown_wheat_plants": grown_wheat_proxy,
        "bought_wheat": bought_wheat,
        "wheat_self_ratio": round(
            grown_wheat_proxy / max(1, grown_wheat_proxy + bought_wheat), 3
        ),
        "early_melon_seeds": early_melon_seeds,
        "day0_animals_total": day0_animals,
        "money_by_day": acc["money_by_day"],
        "daily": acc["daily"],
        "hourly": acc["hourly"],
        "action_log": acc["action_log"],
        "market_log": acc["market_log"],
        "hires_by_day": dict(hires_by_day),
        "sell_rev_by_day": {str(k): round(v, 2) for k, v in acc["sell_rev_by_day"].items()},
        "ops_by_day": {str(k): dict(v) for k, v in acc["ops_by_day"].items()},
    }
    summary["strategies"] = label_strategies(summary)
    return summary


def _fingerprint(orders: list[list[Any]]) -> str:
    parts = []
    for o in orders:
        parts.append("(" + ",".join(str(x) for x in o) + ")")
    return "|".join(parts)


def _second_quadrant_day(unlock_day: dict[str, int]) -> int | None:
    extras = [d for q, d in unlock_day.items() if q != "NW"]
    return min(extras) if extras else None


def extract_episode(
    data: dict[str, Any],
    path: Any = None,
    *,
    sample_daily: bool = True,
    log_actions: bool = True,
    sample_hourly: bool = True,
) -> dict[str, Any]:
    from pathlib import Path

    path_obj = Path(path) if path is not None else None
    eid = episode_id(data, path_obj)
    names = agent_names(data)
    rewards = [float(x) for x in (data.get("rewards") or [0, 0])]
    info = data.get("info") or {}
    cfg = data.get("configuration") or {}

    players = [
        extract_player(
            data, 0,
            sample_daily=sample_daily,
            log_actions=log_actions,
            sample_hourly=sample_hourly,
        ),
        extract_player(
            data, 1,
            sample_daily=sample_daily,
            log_actions=log_actions,
            sample_hourly=sample_hourly,
        ),
    ]

    return {
        "episode_id": eid,
        "path": str(path_obj) if path_obj else None,
        "seed": info.get("seed") or cfg.get("seed"),
        "agents": names,
        "rewards": rewards,
        "statuses": list(data.get("statuses") or []),
        "n_steps": len(data.get("steps") or []),
        "turns_per_day": turns_per_day(data),
        "winner": (
            names[0] if rewards[0] > rewards[1]
            else names[1] if rewards[1] > rewards[0]
            else "tie"
        ),
        "margin": abs(rewards[0] - rewards[1]),
        "players": players,
    }
