"""
Day-30 bank maximizer: wheat bootstrap → goose egg engine → liquidate.

Uses `engine_rules` (live interpreter params) and `state_tile.analyze_farm`
for tile scanning. See docs/STRATEGY.md for the full rationale.
"""

from __future__ import annotations

from . import engine_rules as er
from .state_tile import analyze_farm

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

TARGET_GEESE_BY_QUADS = {1: 6, 2: 10, 3: 14, 4: 18}
WHEAT_FEED_BUFFER_DAYS = 3
MIN_CASH_RESERVE = 200
LATE_PLANT_CUTOFF_DAY = 25
WIND_DOWN_DAY = 27
GOOSE_START_DAY = 4          # wait for first wheat harvests before livestock
MAX_HIRES = 6
EGG_MIN_SELL_PRICE = 30
WHEAT_MIN_SELL_PRICE = 15
PREMIUM_MIN_SELL_PRICE = 80
MAX_COOPS_AHEAD = 1
MAX_GEESE_BUY_PER_TURN = 1


def agent(obs):
    farms = obs.get("farms", [])
    player = obs.get("player", 0)
    private = obs.get("private") or {}
    if not farms or player >= len(farms):
        return {"farmer": ["PASS"], "hands": [], "market": []}

    farm = farms[player]
    day = int(obs.get("day", 0))
    hour = int(obs.get("hour", 0))
    prices = (obs.get("market") or {}).get("prices") or {}

    shed = dict(private.get("shed") or {})
    seeds = dict(private.get("seeds") or {})
    inventories = list(private.get("inventories") or [{}])

    summary = analyze_farm(farm, day)
    units = _unit_positions(farm)
    while len(inventories) < len(units):
        inventories.append({})

    n_geese = sum(1 for _, _, a in summary["structures_occupied"] if a == "GOOSE")
    n_empty_coops = sum(
        1 for x, y in summary["structures_empty"]
        if farm["tiles"][y][x].get("kind") == "COOP"
    )
    n_quads = len(farm.get("unlocked_quadrants") or ["NW"])
    target_geese = TARGET_GEESE_BY_QUADS.get(n_quads, 6)
    if day < GOOSE_START_DAY:
        target_geese = 0

    wheat_plants = sum(1 for _, _, c in summary["plants"] if c == "WHEAT")
    wheat_total = shed.get("WHEAT", 0) + sum(inv.get("WHEAT", 0) for inv in inventories)
    feed_need = max(n_geese, 1) * WHEAT_FEED_BUFFER_DAYS

    market_orders = _build_market_orders(
        farm, day, hour, shed, seeds, prices,
        n_geese, n_empty_coops, target_geese,
        wheat_total, wheat_plants, feed_need, summary, len(units),
    )

    tasks = _build_tasks(
        farm, day, hour, summary, shed, seeds, inventories,
        n_geese, n_empty_coops, target_geese, wheat_total, feed_need,
    )

    actions = _assign_actions(units, inventories, tasks, farm, seeds)

    farmer_action = actions[0] if actions else ["PASS"]
    hands_actions = actions[1:]
    n_hands = len(farm.get("hands") or [])
    while len(hands_actions) < n_hands:
        hands_actions.append(["PASS"])
    hands_actions = hands_actions[:n_hands]

    return {"farmer": farmer_action, "hands": hands_actions, "market": market_orders[:10]}


# ===========================================================================
# Market
# ===========================================================================

def _build_market_orders(
    farm, day, hour, shed, seeds, prices,
    n_geese, n_empty_coops, target_geese,
    wheat_total, wheat_plants, feed_need, summary, n_units,
):
    orders = []
    money = float(farm.get("money", 0))
    hires_today = int(farm.get("hires_today", 0))
    unlocked = farm.get("unlocked_quadrants") or ["NW"]

    # --- Sells ---
    for item, qty in list(shed.items()):
        if qty <= 0:
            continue
        price = int(prices.get(item, 0) or 0)
        sell_qty = qty

        if item in ("GOOSE", "COW", "SHEEP"):
            continue
        if item == "WHEAT":
            keep = 0 if day >= WIND_DOWN_DAY else max(feed_need, n_geese + 1)
            sell_qty = max(0, qty - keep)
            if price < WHEAT_MIN_SELL_PRICE and day < WIND_DOWN_DAY:
                sell_qty = max(0, qty - keep * 2)
        elif item == "EGG":
            if price < EGG_MIN_SELL_PRICE and day < WIND_DOWN_DAY and qty < 15:
                continue
        elif item in er.PREMIUM_PRODUCTS:
            if price < PREMIUM_MIN_SELL_PRICE and day < WIND_DOWN_DAY:
                sell_qty = min(1, qty)
        elif item == "FERTILIZER":
            keep = 3 if day < WIND_DOWN_DAY else 0
            sell_qty = max(0, qty - keep)

        if sell_qty > 0:
            orders.append(["SELL", item, int(sell_qty)])

    # --- Hires early each day ---
    workload = (
        len(summary["unwatered_plants"])
        + len(summary["unfed_animals"]) * 2
        + len(summary["harvestable_plants"])
        + len(summary["structures_occupied"])
        + len(summary["empty"])
        + len(summary["weeds"])
    )
    desired = min(1 + MAX_HIRES, max(2, workload // 5 + 1 + (1 if n_geese else 0)))
    if day >= WIND_DOWN_DAY:
        desired = min(desired, 4)
    hired_pending = 0
    while n_units + hired_pending < desired and hires_today + hired_pending < MAX_HIRES:
        cost = er.hire_cost(hires_today + hired_pending)
        if money < cost:
            break
        orders.append(["HIRE"])
        money -= cost
        hired_pending += 1

    # --- Land ---
    land_cost = er.next_land_cost(unlocked)
    if (
        land_cost is not None
        and 3 <= day <= 18
        and money >= land_cost + MIN_CASH_RESERVE + 500
        and (len(summary["empty"]) < 5 or n_geese >= 3)
    ):
        orders.append(["BUY_LAND"])
        money -= land_cost

    # --- Geese: only with empty coop + feed buffer already in hand ---
    shed_geese = shed.get("GOOSE", 0)
    can_feed_new = wheat_total >= (n_geese + 1) and (wheat_plants + wheat_total) >= (n_geese + 2)
    if (
        day >= GOOSE_START_DAY
        and day <= 22
        and n_empty_coops > shed_geese
        and n_geese + shed_geese < target_geese
        and can_feed_new
    ):
        slots = min(
            MAX_GEESE_BUY_PER_TURN,
            n_empty_coops - shed_geese,
            target_geese - n_geese - shed_geese,
        )
        for _ in range(max(0, slots)):
            cost = er.ANIMALS["GOOSE"]["cost"]
            if money < cost + MIN_CASH_RESERVE:
                break
            orders.append(["BUY_ANIMAL", "GOOSE", 1])
            money -= cost

    # --- Wheat seeds ---
    wheat_seeds = seeds.get("WHEAT", 0)
    empty = len(summary["empty"])
    coop_budget = 0
    if day >= GOOSE_START_DAY and n_geese + n_empty_coops < target_geese:
        coop_budget = min(MAX_COOPS_AHEAD, max(0, target_geese - n_geese - n_empty_coops))
    plantable = max(0, empty - coop_budget)
    want = max(0, plantable - wheat_seeds)
    if day < GOOSE_START_DAY:
        want = max(want, min(empty, 15) - wheat_seeds)
    if day > LATE_PLANT_CUTOFF_DAY:
        want = 0
    for _ in range(min(want, 10)):
        cost = er.CROPS["WHEAT"]["seed"]
        reserve = 0 if day < 3 else MIN_CASH_RESERVE // 2
        if money < cost + reserve:
            break
        orders.append(["BUY_SEED", "WHEAT", 1])
        money -= cost

    # --- Emergency feed purchases ---
    if n_geese > 0 and wheat_total < n_geese and day < WIND_DOWN_DAY:
        need = n_geese - wheat_total
        price = int(prices.get("WHEAT", 25) or 25)
        for _ in range(min(need, 8)):
            if money < price:
                break
            orders.append(["BUY_PRODUCT", "WHEAT", 1])
            money -= price

    return orders[:10]


# ===========================================================================
# Field tasks
# ===========================================================================

def _build_tasks(
    farm, day, hour, summary, shed, seeds, inventories,
    n_geese, n_empty_coops, target_geese, wheat_total, feed_need,
):
    tasks = []
    tiles = farm["tiles"]
    carrying_goose = any(inv.get("GOOSE", 0) > 0 for inv in inventories)
    carrying_wheat = any(inv.get("WHEAT", 0) > 0 for inv in inventories)

    # 1) Water — mandatory (new seeds weed overnight if skipped).
    for x, y in summary["unwatered_plants"]:
        tile = tiles[y][x]
        prio = 200 if tile.get("consecutive_unwatered", 0) >= 1 else 160
        crop = tile["crop"]
        if not er.CROPS[crop]["ongoing"]:
            start, end = er.water_bonus_window(crop)
            age = day - tile["planted_day"]
            if start <= age <= end:
                prio = max(prio, 170)
        tasks.append((prio, x, y, ["WATER"], None))

    # 2) Feed logistics — pickup wheat before feed when nobody is carrying.
    unfed = list(summary["unfed_animals"])
    if unfed and shed.get("WHEAT", 0) > 0 and not carrying_wheat:
        n = min(shed["WHEAT"], max(len(unfed), n_geese))
        sx, sy = er.SHED_ACCESS[0]
        tasks.append((210, sx, sy, ["PICKUP", "WHEAT", n], None))

    for x, y in unfed:
        tasks.append((205, x, y, ["FEED"], {"WHEAT": 1}))

    # 3) Place geese already in shed / inventory.
    if n_empty_coops > 0 and (shed.get("GOOSE", 0) > 0 or carrying_goose):
        if shed.get("GOOSE", 0) > 0 and not carrying_goose:
            sx, sy = er.SHED_ACCESS[0]
            tasks.append((195, sx, sy, ["PICKUP", "GOOSE", 1], None))
        for x, y in summary["structures_empty"]:
            if tiles[y][x].get("kind") == "COOP":
                tasks.append((190, x, y, ["PLACE", "GOOSE"], {"GOOSE": 1}))

    # 4) Harvest animal products (avoid max_held waste).
    for x, y, animal in summary["structures_occupied"]:
        tile = tiles[y][x]
        held = tile.get("yield_units", 0)
        if held <= 0:
            continue
        cap = er.ANIMALS[animal]["max_held"]
        prio = 175 if held >= cap - 1 or day >= WIND_DOWN_DAY else 130
        tasks.append((prio, x, y, ["HARVEST"], None))

    # 5) Care (egg bonus).
    for x, y, _animal in summary["structures_occupied"]:
        tile = tiles[y][x]
        if not tile.get("cared_today"):
            tasks.append((140, x, y, ["CARE"], None))

    # 6) Harvest mature wheat.
    for x, y in summary["harvestable_plants"]:
        tile = tiles[y][x]
        crop = tile["crop"]
        cd = er.CROPS[crop]
        age = day - tile["planted_day"]
        if tile.get("yield_units", 0) <= 0 or age < cd["first_yield_day"]:
            continue
        if cd["ongoing"]:
            tasks.append((135, x, y, ["HARVEST"], None))
        elif age >= cd["max_yield_day"] or day >= WIND_DOWN_DAY or day >= LATE_PLANT_CUTOFF_DAY:
            tasks.append((145, x, y, ["HARVEST"], None))

    # 7) Fertilizer collect / apply.
    for x, y in summary["collectible_fertilizer"]:
        tasks.append((100, x, y, ["COLLECT_FERTILIZER"], None))

    if any(inv.get("FERTILIZER", 0) > 0 for inv in inventories) or shed.get("FERTILIZER", 0) > 0:
        if shed.get("FERTILIZER", 0) > 0 and not any(inv.get("FERTILIZER", 0) > 0 for inv in inventories):
            sx, sy = er.SHED_ACCESS[0]
            tasks.append((98, sx, sy, ["PICKUP", "FERTILIZER", 1], None))
        for x, y, crop in summary["plants"]:
            if crop != "WHEAT":
                continue
            tile = tiles[y][x]
            age = day - tile["planted_day"]
            start, end = er.water_bonus_window(crop)
            if tile.get("fertilized_until_day", -1) >= day:
                continue
            if start - 1 <= age <= end and day < WIND_DOWN_DAY:
                tasks.append((105, x, y, ["FERTILIZE"], {"FERTILIZER": 1}))

    # 8) Dig weeds, and reclaim excess empty coops for wheat.
    for x, y in summary["weeds"]:
        tasks.append((90, x, y, ["DIG"], None))
    if n_empty_coops > MAX_COOPS_AHEAD and day <= LATE_PLANT_CUTOFF_DAY:
        extras = [
            (x, y) for x, y in summary["structures_empty"]
            if tiles[y][x].get("kind") == "COOP"
        ][MAX_COOPS_AHEAD:]
        for x, y in extras:
            tasks.append((85, x, y, ["DIG"], None))

    # 9) Build at most one empty coop ahead of the current flock.
    if day >= GOOSE_START_DAY and day <= 20 and target_geese > 0:
        if n_geese < target_geese and n_empty_coops < MAX_COOPS_AHEAD:
            for x, y in summary["empty"][: max(0, MAX_COOPS_AHEAD - n_empty_coops)]:
                tasks.append((110, x, y, ["BUILD_COOP"], None))

    # 10) Plant wheat on remaining empties.
    wheat_seeds_left = int(seeds.get("WHEAT", 0))
    if day <= LATE_PLANT_CUTOFF_DAY and wheat_seeds_left > 0:
        reserved = {(t[1], t[2]) for t in tasks if t[3][:1] == ["BUILD_COOP"]}
        for x, y in summary["empty"]:
            if wheat_seeds_left <= 0:
                break
            if (x, y) in reserved:
                continue
            tasks.append((80, x, y, ["PLANT", "WHEAT"], None))
            wheat_seeds_left -= 1

    # 11) Soft drop of sellable goods at shed.
    sx, sy = er.SHED_ACCESS[0]
    tasks.append((50, sx, sy, ["DROP"], {"_drop": True}))

    # Early-day bias: first hours focus feed/water over expansion.
    if hour < 6 and n_geese > 0:
        tasks = [(p + 20, x, y, a, n) if a[0] in ("FEED", "WATER", "PICKUP", "CARE") else (p, x, y, a, n)
                 for p, x, y, a, n in tasks]

    tasks.sort(key=lambda t: -t[0])
    return tasks


# ===========================================================================
# Assignment / pathing
# ===========================================================================

def _unit_positions(farm):
    positions = [tuple(farm["farmer"])]
    for h in farm.get("hands") or []:
        positions.append(tuple(h))
    return positions


def _manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _step_toward(pos, target):
    x, y = pos
    tx, ty = target
    if x < tx:
        return ["EAST"]
    if x > tx:
        return ["WEST"]
    if y < ty:
        return ["SOUTH"]
    if y > ty:
        return ["NORTH"]
    return ["PASS"]


def _inv_has(inv, needs):
    if not needs:
        return True
    if needs.get("_drop"):
        return any(v > 0 for v in inv.values())
    for item, n in needs.items():
        if item.startswith("_"):
            continue
        if inv.get(item, 0) < n:
            return False
    return True


def _assign_actions(units, inventories, tasks, farm, seeds=None):
    claimed_tiles = set()
    assigned = [None] * len(units)
    used_units = set()
    seeds_left = dict(seeds or {})
    virt_inv = [dict(inv) for inv in inventories]

    for prio, x, y, action, needs in tasks:
        if (x, y) in claimed_tiles and action[0] not in ("PICKUP", "DROP"):
            continue

        best_i = None
        best_d = 10**9
        for i, pos in enumerate(units):
            if i in used_units:
                continue
            inv = virt_inv[i]

            if action[0] == "DROP":
                carry = {k: v for k, v in inv.items() if v > 0}
                if not carry:
                    continue
                # Keep wheat on hand for feeding; keep goose for placing.
                if set(carry.keys()) <= {"WHEAT"} and prio < 100:
                    continue
                if "GOOSE" in carry:
                    continue

            if action[0] == "FEED" and not _inv_has(inv, {"WHEAT": 1}):
                continue
            if action[0] == "FERTILIZE" and not _inv_has(inv, {"FERTILIZER": 1}):
                continue
            if action[0] == "PLACE" and not _inv_has(inv, {"GOOSE": 1}):
                continue
            if action[0] == "PLANT":
                crop = action[1] if len(action) > 1 else None
                if not crop or seeds_left.get(crop, 0) <= 0:
                    continue
            elif needs and not needs.get("_drop") and not _inv_has(inv, needs):
                continue

            d = _manhattan(pos, (x, y))
            if action[0] == "FEED" and inv.get("WHEAT", 0) > 0:
                d -= 40
            if action[0] == "PLACE" and inv.get("GOOSE", 0) > 0:
                d -= 40
            if action[0] == "FERTILIZE" and inv.get("FERTILIZER", 0) > 0:
                d -= 40
            if d < best_d:
                best_d = d
                best_i = i

        if best_i is None:
            continue

        pos = units[best_i]
        if pos == (x, y):
            assigned[best_i] = action
            if action[0] == "PICKUP" and len(action) >= 2:
                item = action[1]
                n = int(action[2]) if len(action) >= 3 else 1
                virt_inv[best_i][item] = virt_inv[best_i].get(item, 0) + n
            elif action[0] == "FEED":
                virt_inv[best_i]["WHEAT"] = max(0, virt_inv[best_i].get("WHEAT", 1) - 1)
            elif action[0] == "PLACE" and len(action) >= 2:
                item = action[1]
                virt_inv[best_i][item] = max(0, virt_inv[best_i].get(item, 1) - 1)
            elif action[0] == "PLANT" and len(action) >= 2:
                seeds_left[action[1]] = seeds_left.get(action[1], 1) - 1
            elif action[0] == "DROP":
                virt_inv[best_i] = {}
        else:
            assigned[best_i] = _step_toward(pos, (x, y))

        used_units.add(best_i)
        if action[0] not in ("PICKUP", "DROP"):
            claimed_tiles.add((x, y))
        if len(used_units) == len(units):
            break

    for i in range(len(units)):
        if assigned[i] is not None:
            continue
        inv = virt_inv[i]
        if inv.get("GOOSE", 0) > 0:
            empty_coops = [
                (x, y)
                for y, row in enumerate(farm["tiles"])
                for x, t in enumerate(row)
                if isinstance(t, dict) and t.get("kind") == "COOP" and t.get("animal") is None
            ]
            if empty_coops:
                target = min(empty_coops, key=lambda p: _manhattan(units[i], p))
                assigned[i] = ["PLACE", "GOOSE"] if units[i] == target else _step_toward(units[i], target)
                continue
        valuable = {k: v for k, v in inv.items() if v > 0 and k not in ("WHEAT", "GOOSE")}
        if valuable:
            shed_tile = min(er.SHED_ACCESS, key=lambda s: _manhattan(units[i], s))
            assigned[i] = ["DROP"] if units[i] == shed_tile else _step_toward(units[i], shed_tile)
        else:
            assigned[i] = ["PASS"]

    return assigned
