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
MAX_HIRES = 5                # up to farmer + 5 hands when the day is packed
HIRE_UNTIL_HOUR = 3          # top up early if backlog still exceeds crew capacity
BUSY_TURNS_TARGET = 21       # keep crew working ~all day; ~3 turns slack, not idle sixth
JOBS_PER_TURN = 0.72         # after walk overhead
EGG_MIN_SELL_PRICE = 30
WHEAT_MIN_SELL_PRICE = 15
PREMIUM_MIN_SELL_PRICE = 80
MAX_COOPS_AHEAD = 1
MAX_GEESE_BUY_PER_TURN = 1
DIST_PENALTY = 8

# Market timing / shed
SHED_CAPACITY = 100
SHED_SOFT_CAP = 78          # begin pressure-selling before overflow
SHED_HARD_CAP = 92          # force dump regardless of shop timing
WHEAT_STOCK_BUY_MAX = 22    # buy feed when at/under this (base is 25)
WHEAT_STOCK_DAYS = 5        # target days of feed on hand when cheap
FERT_STOCK_BUY_MAX = 70     # fertilizer base 100; stock when discounted
FERT_STOCK_TARGET = 6
EGG_HOLD_UNTIL_DAY = 12     # wait for egg shops unless shed pressure / great price
EGG_GOOD_SELL = 48          # sell freely at/above this even without shop
WHEAT_GOOD_SELL = 24
LIQUIDATE_DAY = 28          # dump remaining sellables into the bank


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
    market_inv = (obs.get("market") or {}).get("inventory") or {}
    unlocked_shops = list((obs.get("town") or {}).get("unlocked_shops") or [])

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
        farm, day, hour, shed, seeds, prices, market_inv, unlocked_shops,
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

# Shops that pull our main cash products (from constants.TOWN_SHOPS).
_PRODUCT_SHOPS = {
    "EGG": ("BAKERY", "BRUNCH_SPOT"),
    "WHEAT": ("BAKERY", "PIZZA_SHOP", "BRUNCH_SPOT", "ICE_CREAM_SHOP", "FARMERS_MARKET"),
    "CARROT": ("PET_CAFE", "FARMERS_MARKET"),
    "TOMATO": ("PIZZA_SHOP", "FARMERS_MARKET"),
    "STRAWBERRY": ("BRUNCH_SPOT", "ICE_CREAM_SHOP", "SMOOTHIE_SHOP", "FARMERS_MARKET"),
    "MILK": ("PIZZA_SHOP", "ICE_CREAM_SHOP", "SMOOTHIE_SHOP"),
    "WOOL": ("YARN_STORE",),
}


def _shed_used(shed):
    return sum(max(0, int(v)) for v in shed.values())


def _shed_room(shed, reserved=0):
    return max(0, SHED_CAPACITY - _shed_used(shed) - reserved)


def _shop_demands(item, unlocked_shops):
    wanted = _PRODUCT_SHOPS.get(item, ())
    return any(s in unlocked_shops for s in wanted)


def _build_market_orders(
    farm, day, hour, shed, seeds, prices, market_inv, unlocked_shops,
    n_geese, n_empty_coops, target_geese,
    wheat_total, wheat_plants, feed_need, summary, n_units,
):
    orders = []
    money = float(farm.get("money", 0))
    hires_today = int(farm.get("hires_today", 0))
    unlocked_land = farm.get("unlocked_quadrants") or ["NW"]
    shed = dict(shed)  # local copy so we can simulate fills

    pressure = _shed_used(shed) >= SHED_SOFT_CAP
    critical = (
        _shed_used(shed) >= SHED_HARD_CAP
        or day >= WIND_DOWN_DAY
        or day >= LIQUIDATE_DAY
    )

    # --- Timed sells (hold for shop demand / good price; dump on shed pressure) ---
    for item, qty in sorted(shed.items(), key=lambda kv: kv[0]):
        if qty <= 0:
            continue
        if item in ("GOOSE", "COW", "SHEEP"):
            continue

        price = int(prices.get(item, 0) or 0)
        sell_qty = 0
        shop_ok = _shop_demands(item, unlocked_shops)

        if item == "WHEAT":
            keep = 0 if critical else max(feed_need, n_geese * WHEAT_STOCK_DAYS // 2, n_geese + 1)
            surplus = max(0, qty - keep)
            if surplus <= 0:
                continue
            if critical or pressure:
                # Free space first; keep a thin feed buffer even under pressure.
                thin_keep = 0 if day >= WIND_DOWN_DAY else max(n_geese, 1)
                sell_qty = max(0, qty - thin_keep)
            elif shop_ok or price >= WHEAT_GOOD_SELL:
                sell_qty = surplus
            elif price >= WHEAT_MIN_SELL_PRICE and surplus > feed_need:
                sell_qty = surplus - feed_need  # drip excess only
            else:
                continue

        elif item == "EGG":
            if critical or pressure:
                # Under pressure sell enough to get under soft cap.
                overflow = max(0, _shed_used(shed) - SHED_SOFT_CAP + 5)
                sell_qty = min(qty, max(overflow, qty // 2 if critical else overflow))
            elif shop_ok or price >= EGG_GOOD_SELL or day >= EGG_HOLD_UNTIL_DAY:
                sell_qty = qty
            elif price >= EGG_MIN_SELL_PRICE and qty > 20:
                sell_qty = qty - 15  # don't let eggs dominate the shed forever
            else:
                continue

        elif item == "FERTILIZER":
            keep = 0 if critical else FERT_STOCK_TARGET
            surplus = max(0, qty - keep)
            if surplus <= 0:
                continue
            if critical or pressure or price >= 90:
                sell_qty = surplus
            else:
                continue

        elif item in er.PREMIUM_PRODUCTS:
            if critical or pressure:
                sell_qty = min(qty, 2)  # drip to avoid $1 floor crash
            elif shop_ok and price >= PREMIUM_MIN_SELL_PRICE:
                sell_qty = min(qty, 3)
            elif price >= PREMIUM_MIN_SELL_PRICE + 40:
                sell_qty = min(qty, 2)
            else:
                continue

        else:
            # Other staples (carrot/tomato/…)
            if critical or pressure or shop_ok or day >= EGG_HOLD_UNTIL_DAY:
                sell_qty = qty
            elif price >= 30:
                sell_qty = qty
            else:
                continue

        if sell_qty > 0:
            orders.append(["SELL", item, int(sell_qty)])
            shed[item] = qty - int(sell_qty)

    # --- Hires ---
    if hour <= HIRE_UNTIL_HOUR:
        desired = _desired_units(day, hour, summary, n_geese)
        hired_pending = 0
        while n_units + hired_pending < desired and hires_today + hired_pending < MAX_HIRES:
            cost = er.hire_cost(hires_today + hired_pending)
            if money < cost:
                break
            orders.append(["HIRE"])
            money -= cost
            hired_pending += 1

    # --- Land ---
    land_cost = er.next_land_cost(unlocked_land)
    if (
        land_cost is not None
        and 3 <= day <= 18
        and money >= land_cost + MIN_CASH_RESERVE + 500
        and (len(summary["empty"]) < 5 or n_geese >= 3)
    ):
        orders.append(["BUY_LAND"])
        money -= land_cost

    # --- Geese ---
    shed_geese = shed.get("GOOSE", 0)
    can_feed_new = wheat_total >= (n_geese + 1) and (wheat_plants + wheat_total) >= (n_geese + 2)
    if (
        day >= GOOSE_START_DAY
        and day <= 22
        and n_empty_coops > shed_geese
        and n_geese + shed_geese < target_geese
        and can_feed_new
        and _shed_room(shed) > 0
    ):
        slots = min(
            MAX_GEESE_BUY_PER_TURN,
            n_empty_coops - shed_geese,
            target_geese - n_geese - shed_geese,
            _shed_room(shed),
        )
        for _ in range(max(0, slots)):
            cost = er.ANIMALS["GOOSE"]["cost"]
            if money < cost + MIN_CASH_RESERVE:
                break
            orders.append(["BUY_ANIMAL", "GOOSE", 1])
            money -= cost
            shed["GOOSE"] = shed.get("GOOSE", 0) + 1

    # --- Wheat seeds (do not use shed space) ---
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

    # --- Opportunistic stock buys while cheap (leave shed headroom for harvests) ---
    room = _shed_room(shed, reserved=12)  # leave room for day's harvest drop
    if day < WIND_DOWN_DAY and room > 0 and n_geese > 0:
        wheat_price = int(prices.get("WHEAT", 25) or 25)
        target_wheat = max(feed_need, n_geese * WHEAT_STOCK_DAYS)
        wheat_gap = max(0, target_wheat - wheat_total)
        if wheat_price <= WHEAT_STOCK_BUY_MAX and wheat_gap > 0:
            buy_n = min(wheat_gap, room, 8)
            for _ in range(buy_n):
                if money < wheat_price + MIN_CASH_RESERVE:
                    break
                if _shed_room(shed, reserved=12) <= 0:
                    break
                orders.append(["BUY_PRODUCT", "WHEAT", 1])
                money -= wheat_price
                shed["WHEAT"] = shed.get("WHEAT", 0) + 1
                wheat_total += 1
                room = _shed_room(shed, reserved=12)

        fert_price = int(prices.get("FERTILIZER", 100) or 100)
        fert_have = shed.get("FERTILIZER", 0)
        if fert_price <= FERT_STOCK_BUY_MAX and fert_have < FERT_STOCK_TARGET and room > 0:
            buy_n = min(FERT_STOCK_TARGET - fert_have, room, 3)
            for _ in range(buy_n):
                if money < fert_price + MIN_CASH_RESERVE:
                    break
                if _shed_room(shed, reserved=12) <= 0:
                    break
                orders.append(["BUY_PRODUCT", "FERTILIZER", 1])
                money -= fert_price
                shed["FERTILIZER"] = shed.get("FERTILIZER", 0) + 1
                room = _shed_room(shed, reserved=12)

    # --- Emergency feed (any price) if animals would starve tonight ---
    if n_geese > 0 and wheat_total < n_geese and day < WIND_DOWN_DAY:
        need = n_geese - wheat_total
        price = int(prices.get("WHEAT", 25) or 25)
        for _ in range(min(need, _shed_room(shed), 8)):
            if money < price:
                break
            orders.append(["BUY_PRODUCT", "WHEAT", 1])
            money -= price
            shed["WHEAT"] = shed.get("WHEAT", 0) + 1
            wheat_total += 1

    return orders[:10]


def _desired_units(day, hour, summary, n_geese):
    """
    Hire the crew size that fills ~BUSY_TURNS_TARGET of the day.

    Too few → backlog / missed water-feed. Too many → finish early and idle.
    desired ≈ ceil(today's tile-jobs / (busy_turns × work_rate)).
    """
    turns_left = max(1, 24 - hour)
    # Shrink the busy window as the day advances so we don't overhire at hour 3
    # for work that no longer exists.
    busy = min(BUSY_TURNS_TARGET, turns_left)
    capacity = max(1, int(busy * JOBS_PER_TURN))

    water = len(summary["unwatered_plants"])
    feed = len(summary["unfed_animals"])
    # Feed + care (+ harvest when ready) — animals are multi-touch.
    animal = feed + n_geese + sum(
        1 for _x, _y, _a in summary["structures_occupied"]
    )  # care pass
    harvest = len(summary["harvestable_plants"])
    weeds = len(summary["weeds"])
    # Count empties we will actually try to plant today (cap only for wind-down).
    empty = len(summary["empty"])
    if day > LATE_PLANT_CUTOFF_DAY:
        plant = 0
    else:
        plant = empty

    jobs = water + animal + harvest + weeds + plant
    desired = max(1, (jobs + capacity - 1) // capacity)

    # Prefer rounding so expected idle stays small:
    # idle_turns ≈ busy - jobs/n/JOBS_PER_TURN. If n is low, idle=0 but backlog;
    # if n is high, idle grows. Stick with ceil unless ceil would leave >6 idle turns.
    if desired > 1:
        idle_if = busy - (jobs / desired) / JOBS_PER_TURN
        if idle_if > 6 and desired > 1:
            # One fewer body still clears the day with less idle.
            alt = desired - 1
            if alt * capacity >= jobs * 0.85:  # still cover most work
                desired = alt

    return min(desired, 1 + MAX_HIRES)


# ===========================================================================
# Field tasks
# ===========================================================================

def _near_shed_key(pos):
    """Sort key: closer to shed first, then snake within equal distance."""
    x, y = pos
    d = min(_manhattan((x, y), s) for s in er.SHED_ACCESS)
    # Boustrophedon within a distance band: even rows L→R, odd R→L.
    return (d, y, x if y % 2 == 0 else -x)


def _build_tasks(
    farm, day, hour, summary, shed, seeds, inventories,
    n_geese, n_empty_coops, target_geese, wheat_total, feed_need,
):
    tasks = []
    tiles = farm["tiles"]
    carrying_goose = any(inv.get("GOOSE", 0) > 0 for inv in inventories)
    carrying_wheat = any(inv.get("WHEAT", 0) > 0 for inv in inventories)

    # Prefer shed-adjacent access tile nearest the flock / plants when picking up.
    shed_tile = _best_shed_tile(summary)

    # 1) Water — mandatory (new seeds weed overnight if skipped).
    water_tiles = sorted(summary["unwatered_plants"], key=_near_shed_key)
    for x, y in water_tiles:
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
    unfed = sorted(summary["unfed_animals"], key=_near_shed_key)
    if unfed and shed.get("WHEAT", 0) > 0 and not carrying_wheat:
        n = min(shed["WHEAT"], max(len(unfed), n_geese))
        sx, sy = shed_tile
        tasks.append((210, sx, sy, ["PICKUP", "WHEAT", n], None))

    for x, y in unfed:
        tasks.append((205, x, y, ["FEED"], {"WHEAT": 1}))

    # 3) Place geese already in shed / inventory.
    if n_empty_coops > 0 and (shed.get("GOOSE", 0) > 0 or carrying_goose):
        if shed.get("GOOSE", 0) > 0 and not carrying_goose:
            sx, sy = shed_tile
            tasks.append((195, sx, sy, ["PICKUP", "GOOSE", 1], None))
        empty_coops = sorted(
            [(x, y) for x, y in summary["structures_empty"] if tiles[y][x].get("kind") == "COOP"],
            key=_near_shed_key,
        )
        for x, y in empty_coops:
            tasks.append((190, x, y, ["PLACE", "GOOSE"], {"GOOSE": 1}))

    # 4) Harvest animal products (avoid max_held waste).
    for x, y, animal in sorted(summary["structures_occupied"], key=lambda t: _near_shed_key((t[0], t[1]))):
        tile = tiles[y][x]
        held = tile.get("yield_units", 0)
        if held <= 0:
            continue
        cap = er.ANIMALS[animal]["max_held"]
        prio = 175 if held >= cap - 1 or day >= WIND_DOWN_DAY else 130
        tasks.append((prio, x, y, ["HARVEST"], None))

    # 5) Care (egg bonus).
    for x, y, _animal in sorted(summary["structures_occupied"], key=lambda t: _near_shed_key((t[0], t[1]))):
        tile = tiles[y][x]
        if not tile.get("cared_today"):
            tasks.append((140, x, y, ["CARE"], None))

    # 6) Harvest mature wheat.
    for x, y in sorted(summary["harvestable_plants"], key=_near_shed_key):
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
    for x, y in sorted(summary["collectible_fertilizer"], key=_near_shed_key):
        tasks.append((100, x, y, ["COLLECT_FERTILIZER"], None))

    if any(inv.get("FERTILIZER", 0) > 0 for inv in inventories) or shed.get("FERTILIZER", 0) > 0:
        if shed.get("FERTILIZER", 0) > 0 and not any(inv.get("FERTILIZER", 0) > 0 for inv in inventories):
            sx, sy = shed_tile
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
    for x, y in sorted(summary["weeds"], key=_near_shed_key):
        tasks.append((90, x, y, ["DIG"], None))
    if n_empty_coops > MAX_COOPS_AHEAD and day <= LATE_PLANT_CUTOFF_DAY:
        extras = sorted(
            [(x, y) for x, y in summary["structures_empty"] if tiles[y][x].get("kind") == "COOP"],
            key=_near_shed_key,
        )[MAX_COOPS_AHEAD:]
        # Dig farthest excess first (keep coops near shed).
        for x, y in reversed(extras):
            tasks.append((85, x, y, ["DIG"], None))

    # 9) Build coop near shed when expanding flock.
    if day >= GOOSE_START_DAY and day <= 20 and target_geese > 0:
        if n_geese < target_geese and n_empty_coops < MAX_COOPS_AHEAD:
            near_empty = sorted(summary["empty"], key=_near_shed_key)
            for x, y in near_empty[: max(0, MAX_COOPS_AHEAD - n_empty_coops)]:
                tasks.append((110, x, y, ["BUILD_COOP"], None))

    # 10) Plant wheat — fill outward from shed (not top-row-first).
    wheat_seeds_left = int(seeds.get("WHEAT", 0))
    if day <= LATE_PLANT_CUTOFF_DAY and wheat_seeds_left > 0:
        reserved = {(t[1], t[2]) for t in tasks if t[3][:1] == ["BUILD_COOP"]}
        for x, y in sorted(summary["empty"], key=_near_shed_key):
            if wheat_seeds_left <= 0:
                break
            if (x, y) in reserved:
                continue
            tasks.append((80, x, y, ["PLANT", "WHEAT"], None))
            wheat_seeds_left -= 1

    # 11) Soft drop of sellable goods at shed.
    sx, sy = shed_tile
    tasks.append((50, sx, sy, ["DROP"], {"_drop": True}))

    # Early-day bias: first hours focus feed/water over expansion.
    if hour < 6 and n_geese > 0:
        tasks = [(p + 20, x, y, a, n) if a[0] in ("FEED", "WATER", "PICKUP", "CARE") else (p, x, y, a, n)
                 for p, x, y, a, n in tasks]

    # Stable sort by priority; spatial order within same priority already applied above.
    tasks.sort(key=lambda t: -t[0])
    return tasks


def _best_shed_tile(summary):
    """Pick the shed-access tile closest to current fieldwork."""
    anchors = summary["unfed_animals"] or summary["unwatered_plants"] or summary["structures_occupied"]
    if not anchors:
        return er.SHED_ACCESS[0]
    pts = [(a[0], a[1]) for a in anchors]
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return min(er.SHED_ACCESS, key=lambda s: abs(s[0] - cx) + abs(s[1] - cy))


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
    """
    Task-first: walk the priority list (already near-shed ordered within a
    priority band) and give each job to the closest capable free unit.
    That stops everyone marching to row 0, then working downward.
    """
    claimed = set()
    assigned = [None] * len(units)
    used = set()
    seeds_left = dict(seeds or {})
    virt_inv = [dict(inv) for inv in inventories]

    for prio, x, y, action, needs in tasks:
        if (x, y) in claimed and action[0] not in ("PICKUP", "DROP"):
            continue

        best_i = None
        best_d = 10**9
        for i, pos in enumerate(units):
            if i in used:
                continue
            inv = virt_inv[i]
            if not _unit_can_do(inv, action, needs, seeds_left, prio):
                continue
            d = _manhattan(pos, (x, y))
            if action[0] == "FEED" and inv.get("WHEAT", 0) > 0:
                d -= 5
            if action[0] == "PLACE" and inv.get("GOOSE", 0) > 0:
                d -= 5
            if action[0] == "FERTILIZE" and inv.get("FERTILIZER", 0) > 0:
                d -= 5
            if d < best_d:
                best_d = d
                best_i = i

        if best_i is None:
            continue

        pos = units[best_i]
        if pos == (x, y):
            assigned[best_i] = action
            _apply_virtual(virt_inv, best_i, action, seeds_left)
        else:
            assigned[best_i] = _step_toward(pos, (x, y))

        used.add(best_i)
        if action[0] not in ("PICKUP", "DROP"):
            claimed.add((x, y))
        if len(used) == len(units):
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


def _unit_can_do(inv, action, needs, seeds_left, prio):
    if action[0] == "DROP":
        carry = {k: v for k, v in inv.items() if v > 0}
        if not carry:
            return False
        if set(carry.keys()) <= {"WHEAT"} and prio < 100:
            return False
        if "GOOSE" in carry:
            return False
        return True
    if action[0] == "FEED" and not _inv_has(inv, {"WHEAT": 1}):
        return False
    if action[0] == "FERTILIZE" and not _inv_has(inv, {"FERTILIZER": 1}):
        return False
    if action[0] == "PLACE" and not _inv_has(inv, {"GOOSE": 1}):
        return False
    if action[0] == "PLANT":
        crop = action[1] if len(action) > 1 else None
        if not crop or seeds_left.get(crop, 0) <= 0:
            return False
        return True
    if needs and not needs.get("_drop") and not _inv_has(inv, needs):
        return False
    return True


def _apply_virtual(virt_inv, i, action, seeds_left):
    if action[0] == "PICKUP" and len(action) >= 2:
        item = action[1]
        n = int(action[2]) if len(action) >= 3 else 1
        virt_inv[i][item] = virt_inv[i].get(item, 0) + n
    elif action[0] == "FEED":
        virt_inv[i]["WHEAT"] = max(0, virt_inv[i].get("WHEAT", 1) - 1)
    elif action[0] == "PLACE" and len(action) >= 2:
        item = action[1]
        virt_inv[i][item] = max(0, virt_inv[i].get(item, 1) - 1)
    elif action[0] == "PLANT" and len(action) >= 2:
        seeds_left[action[1]] = seeds_left.get(action[1], 1) - 1
    elif action[0] == "DROP":
        virt_inv[i] = {}


def _step_toward(pos, target):
    """Move on the longer axis first to cut corner-cutting zigzags."""
    x, y = pos
    tx, ty = target
    dx, dy = tx - x, ty - y
    if dx == 0 and dy == 0:
        return ["PASS"]
    if abs(dx) >= abs(dy):
        return ["EAST"] if dx > 0 else ["WEST"]
    return ["SOUTH"] if dy > 0 else ["NORTH"]
