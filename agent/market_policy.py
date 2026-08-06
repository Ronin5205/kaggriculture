"""Market-order policy — Melon–Dairy Compound strategy."""

from .constants import (
    MELON_WAVE1,
    MELON_WAVE2,
    TARGET_COWS,
    TARGET_SHEEP,
    WHEAT_FEED_TILES,
    WAVE1_END_DAY,
    WAVE2_END_DAY,
    NO_LONG_CROP_AFTER_DAY,
    SHORT_CYCLE_DAY,
    CASHOUT_DAY,
    CASHOUT_FORCE_FLOOR_TURNS,
    LAND_BUY_DAY,
    LAND_ORDER,
    LAND_COSTS,
    SELL_BATCH,
    SELL_PRICE_FLOOR_FRAC,
    SELL_ABSOLUTE_MIN,
    OBJECT_TYPES,
    MARKET_PARAMS,
    FIBONACCI_HIRE_SEQUENCE,
    PRICE_FLOOR,
    TURNS_PER_DAY,
    MAX_HIRES_PER_TURN,
    target_hands,
)

MAX_ANIMALS_PER_TURN = 2
MIN_CASH_BUFFER = 80
# Keep enough cash for a small hire crew even when broke on feed/seeds
HIRE_CASH_RESERVE = 40


def _hire_cost(hires_today):
    if hires_today < len(FIBONACCI_HIRE_SEQUENCE):
        return FIBONACCI_HIRE_SEQUENCE[hires_today]
    a, b = FIBONACCI_HIRE_SEQUENCE[-2], FIBONACCI_HIRE_SEQUENCE[-1]
    n = hires_today - (len(FIBONACCI_HIRE_SEQUENCE) - 1)
    for _ in range(n):
        a, b = b, a + b
    return b


def _base_price(item):
    if item in MARKET_PARAMS:
        return MARKET_PARAMS[item]["base"]
    return 1


def _should_sell(item, price, force_cashout=False):
    if price is None:
        return False
    if force_cashout:
        return price >= PRICE_FLOOR
    abs_min = SELL_ABSOLUTE_MIN.get(item)
    if abs_min is not None:
        return price >= abs_min
    floor = max(PRICE_FLOOR, int(_base_price(item) * SELL_PRICE_FLOOR_FRAC))
    return price > floor


def _count_in_inv(inventories, item):
    total = 0
    for inv in inventories or []:
        if isinstance(inv, dict):
            total += inv.get(item, 0)
    return total


def build_market_orders(obs, summary):
    player = obs.get("player", 0)
    me = obs["farms"][player]
    private = obs.get("private") or {}
    day = int(obs.get("day", 0) or 0)
    hour = int(obs.get("hour", 0) or 0)
    step = int(obs.get("step", day * TURNS_PER_DAY + hour) or 0)
    market_state = obs.get("market") or {}
    prices = market_state.get("prices") or {}
    money = float(me.get("money", 0) or 0)
    shed = dict(private.get("shed") or {})
    seeds = dict(private.get("seeds") or {})
    inventories = private.get("inventories") or []
    hires_today = int(me.get("hires_today", 0) or 0)
    hands = me.get("hands") or []
    unlocked = list(me.get("unlocked_quadrants") or ["NW"])
    max_orders = 10

    animal_counts = summary.get("animal_counts") or {}
    crop_counts = summary.get("crop_counts") or {}
    n_cows = animal_counts.get("COW", 0)
    n_sheep = animal_counts.get("SHEEP", 0)
    n_plants = sum(crop_counts.values())
    melon_plants = crop_counts.get("MELON", 0)
    wheat_plants = crop_counts.get("WHEAT", 0)

    shed_cows = int(shed.get("COW", 0) or 0)
    shed_sheep = int(shed.get("SHEEP", 0) or 0)
    inv_cows = _count_in_inv(inventories, "COW")
    inv_sheep = _count_in_inv(inventories, "SHEEP")
    n_animals = n_cows + n_sheep
    unfed = len(summary.get("unfed_animals") or [])

    cows_owned = n_cows + shed_cows + inv_cows
    sheep_owned = n_sheep + shed_sheep + inv_sheep
    pending_animals = shed_cows + shed_sheep + inv_cows + inv_sheep
    feed_need_heads = n_animals + pending_animals

    # Phase flags
    in_cashout = day >= CASHOUT_DAY
    force_floor = in_cashout and (
        day > CASHOUT_DAY
        or hour >= TURNS_PER_DAY - CASHOUT_FORCE_FLOOR_TURNS
        or step >= TURNS_PER_DAY * 30 - CASHOUT_FORCE_FLOOR_TURNS
    )
    allow_long_crops = day <= NO_LONG_CROP_AFTER_DAY
    # Melon / cow targets by phase — delay full herd until wave-2 is mostly down
    if day <= 5:
        melon_target = MELON_WAVE1
        cow_target = 2
    elif day <= WAVE1_END_DAY:
        melon_target = MELON_WAVE1
        cow_target = 3
    elif day <= WAVE2_END_DAY:
        melon_target = MELON_WAVE2
        if day <= 14:
            cow_target = 5
        elif day <= 18:
            cow_target = 8
        else:
            cow_target = TARGET_COWS
    else:
        melon_target = 0
        cow_target = TARGET_COWS

    orders = []
    spent = 0.0

    def can_afford(cost, buffer=MIN_CASH_BUFFER):
        return money - spent - cost >= buffer

    def pay(cost):
        nonlocal spent
        spent += cost

    def slots_left():
        return max_orders - len(orders)

    wheat_price = float(prices.get("WHEAT", _base_price("WHEAT")) or 25)
    feed_wheat = int(shed.get("WHEAT", 0) or 0) + _count_in_inv(inventories, "WHEAT")

    # --- Day-0 melon seeds FIRST (capital engine) before feed/cows eat the budget ---
    melon_seeds_ordered = 0
    if day == 0 and allow_long_crops and slots_left() > 0 and not in_cashout:
        have = int(seeds.get("MELON", 0) or 0) + melon_plants
        gap = MELON_WAVE1 - have
        if gap > 0:
            cost = OBJECT_TYPES["MELON"]["seed_cost"]
            n = min(gap, 12)
            while n > 0 and money - spent < cost * n + 400:
                n -= 1
            if n > 0:
                orders.append(["BUY_SEED", "MELON", n])
                pay(cost * n)
                melon_seeds_ordered = n

    # --- Endgame: sell-first cashout ---
    sell_priority = [
        "FERTILIZER", "MILK", "MELON", "WOOL", "STRAWBERRY", "WHEAT",
        "EGG", "TOMATO", "CARROT",
    ]
    # Feed stock target — must match wheat sell reserve or we thrash buy/sell.
    feed_target = 0
    if feed_need_heads or unfed:
        feed_target = max(feed_need_heads + 1, unfed + 1)
    if day < 10 and feed_need_heads > 0:
        # Modest bridge only — grow wheat tiles for the rest
        feed_target = max(feed_target, feed_need_heads * 2 + 2)
    wheat_reserve = feed_target
    if force_floor:
        wheat_reserve = unfed
    elif in_cashout:
        wheat_reserve = feed_need_heads
    # Do not sell feed wheat until short-cycle surplus or cashout
    allow_wheat_sell = in_cashout or day >= SHORT_CYCLE_DAY or wheat_plants >= WHEAT_FEED_TILES

    def emit_sells(aggressive=False):
        for item in sell_priority:
            if slots_left() <= 0:
                break
            qty = int(shed.get(item, 0) or 0)
            if item == "WHEAT":
                if not allow_wheat_sell and not aggressive:
                    continue
                qty = max(0, qty - wheat_reserve)
            if qty <= 0:
                continue
            price = prices.get(item)
            if not _should_sell(item, price, force_cashout=force_floor or aggressive):
                continue
            batch = min(SELL_BATCH.get(item, 4), qty)
            if item == "MELON" and qty >= 16 and not in_cashout:
                batch = min(max(batch, 8), qty, 12)
            if in_cashout:
                batch = min(max(batch, SELL_BATCH.get(item, 4)), qty)
            if batch > 0:
                orders.append(["SELL", item, batch])
                shed[item] = int(shed.get(item, 0) or 0) - batch
        # Melon payday: multiple sell orders while inventory is high
        while slots_left() > 0:
            qty = int(shed.get("MELON", 0) or 0)
            if qty <= 0:
                break
            price = prices.get("MELON")
            if not _should_sell("MELON", price, force_cashout=force_floor or aggressive):
                break
            batch = min(8, qty)
            orders.append(["SELL", "MELON", batch])
            shed["MELON"] = qty - batch

    if in_cashout:
        emit_sells(aggressive=True)

    # --- 1. Critical feed only (gap to unfed+1), keep hire reserve ---
    critical_feed = max(unfed + 1, feed_need_heads) if (feed_need_heads or unfed) else 0
    if critical_feed > feed_wheat and slots_left() > 0 and not (in_cashout and day >= 29):
        n = min(critical_feed - feed_wheat, 6)
        while n > 0 and money - spent - wheat_price * n < HIRE_CASH_RESERVE:
            n -= 1
        if n > 0:
            orders.append(["BUY_PRODUCT", "WHEAT", n])
            pay(wheat_price * n)
            feed_wheat += n

    # --- 1b. Hire early so planting/watering is not starved ---
    if not in_cashout:
        _add_hires(
            orders, spent, money, hands, hires_today, n_animals,
            max(n_plants, melon_target if allow_long_crops else n_plants),
            slots_left, pay, max_orders, day=day,
            pending_cows=shed_cows + inv_cows,
        )

    if in_cashout:
        _add_hires(
            orders, spent, money, hands, hires_today, n_animals, n_plants,
            slots_left, pay, max_orders, day=day, pending_cows=shed_cows + inv_cows,
        )
        emit_sells(aggressive=True)
        return orders[:max_orders]

    # Metered sells early — free cash for seeds/cows/hires
    emit_sells(aggressive=False)

    # --- 2. Melon seeds (capital engine) — don't overbuy beyond plantable labor ---
    if allow_long_crops and slots_left() > 0 and melon_target > 0:
        have = int(seeds.get("MELON", 0) or 0) + melon_plants + melon_seeds_ordered
        gap = melon_target - have
        if gap > 0:
            cost = OBJECT_TYPES["MELON"]["seed_cost"]
            empties = len(summary.get("empty") or [])
            n = min(gap, 12 if day == 0 else 6, max(empties, 1))
            buf = 50 if day <= 1 else max(MIN_CASH_BUFFER, 150 + n_animals * 25)
            while n > 0 and not can_afford(cost * n, buffer=buf):
                n -= 1
            if n > 0:
                orders.append(["BUY_SEED", "MELON", n])
                pay(cost * n)
                melon_seeds_ordered += n

    # Top-up feed toward feed_target after seeds (non-critical)
    if feed_target > feed_wheat and slots_left() > 0 and day < WAVE1_END_DAY:
        n = min(feed_target - feed_wheat, 4)
        while n > 0 and not can_afford(wheat_price * n, buffer=HIRE_CASH_RESERVE):
            n -= 1
        if n > 0:
            orders.append(["BUY_PRODUCT", "WHEAT", n])
            pay(wheat_price * n)
            feed_wheat += n

    # --- 3. Cows (defer until wave-1 melons are mostly planted) ---
    animals_bought = 0
    cow_gap = cow_target - cows_owned
    melons_ready = melon_plants + int(seeds.get("MELON", 0) or 0) >= MELON_WAVE1 - 2
    # Don't buy cows while broke or before housing existing shed stock
    can_buy_cows = (
        cow_gap > 0
        and slots_left() > 0
        and shed_cows + inv_cows <= 1
        and (day > WAVE1_END_DAY or (cows_owned < 2 and (day >= 1 or melons_ready)))
        and money - spent > (800 if day > WAVE1_END_DAY else 300)
        and (day >= 2 or melon_plants >= 8 or day > 0 and melons_ready)
    )
    if can_buy_cows:
        cost = OBJECT_TYPES["COW"]["seed_cost"]
        n = 0
        while (
            n < cow_gap
            and animals_bought + n < MAX_ANIMALS_PER_TURN
            and can_afford(cost * (n + 1) + wheat_price, buffer=100)
        ):
            n += 1
        if n > 0:
            orders.append(["BUY_ANIMAL", "COW", n])
            pay(cost * n)
            animals_bought += n
            feed_need_heads += n

    # Optional late sheep only if rich and tiles free (plan: usually 0)
    if (
        TARGET_SHEEP > 0
        and day >= 15
        and money - spent > 15000
        and sheep_owned < TARGET_SHEEP
        and slots_left() > 0
        and animals_bought < MAX_ANIMALS_PER_TURN
    ):
        cost = OBJECT_TYPES["SHEEP"]["seed_cost"]
        if can_afford(cost + wheat_price):
            orders.append(["BUY_ANIMAL", "SHEEP", 1])
            pay(cost)
            animals_bought += 1

    # Keep herd fed — escape is permanent; buy ahead when scaling
    if feed_need_heads > 0 and slots_left() > 0:
        need_feed = max(feed_need_heads + 3, n_animals + pending_animals + 2)
        if day >= 12:
            need_feed = max(need_feed, n_animals * 2)
        if feed_wheat < need_feed:
            n = min(need_feed - feed_wheat, 10)
            while n > 0 and money - spent < wheat_price * n:
                n -= 1
            if n > 0:
                orders.append(["BUY_PRODUCT", "WHEAT", n])
                pay(wheat_price * n)
                feed_wheat += n

    # --- 4. Wheat seeds (grow feed; more in short-cycle phase) ---
    if slots_left() > 0:
        want_wheat = WHEAT_FEED_TILES
        if day >= SHORT_CYCLE_DAY:
            want_wheat = max(want_wheat, 8)  # short-cycle income tiles
        have = int(seeds.get("WHEAT", 0) or 0) + wheat_plants
        gap = want_wheat - have
        if gap > 0:
            cost = OBJECT_TYPES["WHEAT"]["seed_cost"]
            n = min(gap, 6)
            while n > 0 and not can_afford(cost * n):
                n -= 1
            if n > 0:
                orders.append(["BUY_SEED", "WHEAT", n])
                pay(cost * n)

    # Land NE then SW when tile-short for wave 2 (after melon payday)
    if (
        day >= LAND_BUY_DAY
        and (day > WAVE1_END_DAY or money - spent > 4000)
        and slots_left() > 0
        and money - spent > 1500
    ):
        empties = len(summary.get("empty") or [])
        seeds_m = int(seeds.get("MELON", 0) or 0)
        need_tiles = (
            (melon_target > melon_plants and seeds_m > empties - 4)
            or empties < 8
            or (day > WAVE1_END_DAY and "NE" not in unlocked and money - spent > 2500)
        )
        if need_tiles:
            for q in LAND_ORDER:
                if q in unlocked:
                    continue
                extras = len(unlocked) - 1
                if 0 <= extras < len(LAND_COSTS):
                    cost = LAND_COSTS[extras]
                    buf = 800 if day <= WAVE1_END_DAY + 2 else 500
                    if can_afford(cost, buffer=buf):
                        orders.append(["BUY_LAND"])
                        pay(cost)
                        unlocked.append(q)
                break

    # --- 6. Top-up hires after spends (workload may have grown) ---
    _add_hires(
        orders, spent, money, hands, hires_today, n_animals, max(n_plants, melon_target),
        slots_left, pay, max_orders, day=day,
        pending_cows=shed_cows + inv_cows + animals_bought,
    )

    return orders[:max_orders]


def _add_hires(orders, spent, money, hands, hires_today, n_animals, n_plants,
               slots_left, pay, max_orders, day=0, pending_cows=0):
    """Hire toward workload target; spend freely for min crew."""
    want = target_hands(n_animals + pending_cows, n_plants)
    # Melon rush: need bodies to plant/water 12 melons
    if day <= 2:
        want = max(want, 8)
    elif n_plants >= 8:
        want = max(want, 6)
    already = sum(1 for o in orders if o and o[0] == "HIRE")
    hires_added = 0
    min_crew = min(want, max(4, n_animals + pending_cows + 2)) if (
        n_animals or pending_cows or n_plants or day == 0
    ) else 0

    while (
        len(hands) + already + hires_added < want
        and hires_added < MAX_HIRES_PER_TURN
        and slots_left() > 0
    ):
        cost = _hire_cost(hires_today + already + hires_added)
        need_min = len(hands) + already + hires_added < min_crew
        if need_min:
            if money - spent < cost:
                break
        elif money - spent - cost < MIN_CASH_BUFFER:
            break
        orders.append(["HIRE"])
        pay(cost)
        hires_added += 1
