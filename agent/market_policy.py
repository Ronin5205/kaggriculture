"""Market-order policy — Labor–Herd Compound strategy."""

from .constants import (
    MELON_WAVE1,
    MELON_WAVE2,
    TARGET_COWS,
    TARGET_SHEEP,
    WHEAT_FEED_TILES,
    STRAWBERRY_WAVE1,
    STRAWBERRY_TARGET,
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
    DAY0_HIRES,
    DAY0_MELON_SEEDS,
    DAY0_WHEAT_SEEDS,
    DAY0_COWS,
    DAY0_SHEEP,
    target_hands,
)

MAX_ANIMALS_PER_TURN = 2
MIN_CASH_BUFFER = 80
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


def _sheep_target(day):
    if day <= 8:
        return 2
    if day <= 12:
        return 4
    if day <= 16:
        return 6
    if day <= 20:
        return 8
    return TARGET_SHEEP


def _cow_target(day):
    if day <= 8:
        return 2
    if day <= 12:
        return 4
    if day <= 16:
        return 6
    if day <= 20:
        return 8
    return TARGET_COWS


def _strawberry_target(day, melon_plants):
    if day > NO_LONG_CROP_AFTER_DAY:
        return 0
    if day <= 3:
        return 0
    if day <= WAVE1_END_DAY:
        # Start straw once wave-1 melons are mostly down
        if melon_plants >= MELON_WAVE1 - 1:
            return STRAWBERRY_WAVE1
        return 0
    if day <= 16:
        return 24
    return STRAWBERRY_TARGET


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
    straw_plants = crop_counts.get("STRAWBERRY", 0)

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

    in_cashout = day >= CASHOUT_DAY
    force_floor = in_cashout and (
        day > CASHOUT_DAY
        or hour >= TURNS_PER_DAY - CASHOUT_FORCE_FLOOR_TURNS
        or step >= TURNS_PER_DAY * 30 - CASHOUT_FORCE_FLOOR_TURNS
    )
    allow_long_crops = day <= NO_LONG_CROP_AFTER_DAY

    if day <= WAVE1_END_DAY:
        melon_target = MELON_WAVE1
    elif day <= WAVE2_END_DAY and allow_long_crops:
        melon_target = MELON_WAVE2
    else:
        melon_target = 0

    cow_target = _cow_target(day)
    sheep_target = _sheep_target(day)
    straw_target = _strawberry_target(day, melon_plants)

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

    # --- Day-0 pack: 6 HIRE + MELON6 + WHEAT12 + COW2 + SHEEP2 (10 orders) ---
    # Trigger on first market turn of the game (hires/animals still zero).
    if (
        day == 0
        and not in_cashout
        and hires_today == 0
        and len(hands) == 0
        and cows_owned == 0
        and sheep_owned == 0
    ):
        day0 = _day0_opening(money, seeds, hires_today, len(hands))
        if day0:
            return day0

    sell_priority = [
        "FERTILIZER", "MILK", "WOOL", "STRAWBERRY", "MELON", "WHEAT",
        "EGG", "TOMATO", "CARROT",
    ]
    feed_target = 0
    if feed_need_heads or unfed:
        feed_target = max(feed_need_heads + 1, unfed + 1)
    if day < 12 and feed_need_heads > 0:
        feed_target = max(feed_target, feed_need_heads + 3)
    wheat_reserve = feed_target
    if force_floor:
        wheat_reserve = unfed
    elif in_cashout:
        wheat_reserve = feed_need_heads
    allow_wheat_sell = in_cashout or day >= SHORT_CYCLE_DAY or wheat_plants >= WHEAT_FEED_TILES

    # Cash crunch: sell hard so we can keep buying feed (escape is permanent).
    cash_crunch = (money < max(400, feed_need_heads * wheat_price + 100)) or unfed > 0

    def emit_sells(aggressive=False):
        force = force_floor or aggressive or cash_crunch
        for item in sell_priority:
            if slots_left() <= 0:
                break
            qty = int(shed.get(item, 0) or 0)
            if item == "WHEAT":
                if not allow_wheat_sell and not force:
                    continue
                qty = max(0, qty - wheat_reserve)
            if qty <= 0:
                continue
            price = prices.get(item)
            if force and price is not None and float(price) >= PRICE_FLOOR:
                ok = True
            else:
                ok = _should_sell(item, price, force_cashout=False)
            if not ok:
                continue
            batch = min(SELL_BATCH.get(item, 4), qty)
            if force:
                batch = min(max(batch, SELL_BATCH.get(item, 4)), qty)
            if item == "MELON" and qty >= 16 and not force:
                batch = min(max(batch, 8), qty, 12)
            if batch > 0:
                orders.append(["SELL", item, batch])
                shed[item] = int(shed.get(item, 0) or 0) - batch
                # Approximate cash from sell for subsequent afford checks
                pay(-float(price or 0) * batch)
        while slots_left() > 0:
            qty = int(shed.get("MELON", 0) or 0)
            if qty <= 0:
                break
            price = prices.get("MELON")
            if force and price is not None and float(price) >= PRICE_FLOOR:
                ok = True
            else:
                ok = _should_sell("MELON", price, force_cashout=False)
            if not ok:
                break
            batch = min(8, qty)
            orders.append(["SELL", "MELON", batch])
            shed["MELON"] = qty - batch
            pay(-float(price or 0) * batch)

    # Sell first when crunching or always lightly — frees cash before spends
    if in_cashout or cash_crunch:
        emit_sells(aggressive=True)
    else:
        emit_sells(aggressive=False)

    # Critical feed (after sells)
    critical_feed = max(unfed + 1, feed_need_heads) if (feed_need_heads or unfed) else 0
    if critical_feed > feed_wheat and slots_left() > 0 and not (in_cashout and day >= 29):
        n = min(critical_feed - feed_wheat, 8)
        while n > 0 and money - spent - wheat_price * n < 0:
            n -= 1
        if n > 0:
            orders.append(["BUY_PRODUCT", "WHEAT", n])
            pay(wheat_price * n)
            feed_wheat += n

    # Hire early — labor for herd CARE + crops
    if not in_cashout and not cash_crunch:
        _add_hires(
            orders, spent, money, hands, hires_today, n_animals,
            max(n_plants, melon_target if allow_long_crops else n_plants, straw_plants),
            slots_left, pay, max_orders, day=day,
            pending_animals=pending_animals,
        )
    elif not in_cashout:
        # Still keep a skeleton crew while crunching
        _add_hires(
            orders, spent, money, hands, hires_today, n_animals, n_plants,
            slots_left, pay, max_orders, day=day,
            pending_animals=pending_animals,
        )

    if in_cashout:
        _add_hires(
            orders, spent, money, hands, hires_today, n_animals, n_plants,
            slots_left, pay, max_orders, day=day, pending_animals=pending_animals,
        )
        emit_sells(aggressive=True)
        return orders[:max_orders]

    feed_budget = feed_need_heads * wheat_price + 150

    # Melon seeds (wave fill — not day-0 pack; day 0 already bought 6)
    if (
        allow_long_crops and slots_left() > 0 and melon_target > 0 and day > 0
        and money - spent > feed_budget + 200
        and not cash_crunch
    ):
        have = int(seeds.get("MELON", 0) or 0) + melon_plants
        gap = melon_target - have
        if gap > 0:
            cost = OBJECT_TYPES["MELON"]["seed_cost"]
            empties = len(summary.get("empty") or [])
            n = min(gap, 4, max(empties, 1))
            buf = max(feed_budget, 200 + n_animals * 20)
            while n > 0 and not can_afford(cost * n, buffer=buf):
                n -= 1
            if n > 0:
                orders.append(["BUY_SEED", "MELON", n])
                pay(cost * n)

    # Strawberry seeds
    if (
        allow_long_crops and straw_target > 0 and slots_left() > 0
        and money - spent > feed_budget + 300
        and not cash_crunch
    ):
        have = int(seeds.get("STRAWBERRY", 0) or 0) + straw_plants
        gap = straw_target - have
        if gap > 0:
            cost = OBJECT_TYPES["STRAWBERRY"]["seed_cost"]
            empties = len(summary.get("empty") or [])
            n = min(gap, 3 if day <= WAVE1_END_DAY else 4, max(empties, 1))
            buf = max(feed_budget, 250 + n_animals * 20)
            while n > 0 and not can_afford(cost * n, buffer=buf):
                n -= 1
            if n > 0:
                orders.append(["BUY_SEED", "STRAWBERRY", n])
                pay(cost * n)

    # Top-up feed
    if feed_target > feed_wheat and slots_left() > 0:
        n = min(feed_target - feed_wheat, 6)
        while n > 0 and money - spent < wheat_price * n:
            n -= 1
        if n > 0:
            orders.append(["BUY_PRODUCT", "WHEAT", n])
            pay(wheat_price * n)
            feed_wheat += n

    # Scale cows
    animals_bought = 0
    cow_gap = cow_target - cows_owned
    can_buy_cows = (
        cow_gap > 0
        and slots_left() > 0
        and shed_cows + inv_cows <= 1
        and not cash_crunch
        and money - spent > feed_budget + 500
    )
    if can_buy_cows:
        cost = OBJECT_TYPES["COW"]["seed_cost"]
        n = 0
        while (
            n < cow_gap
            and animals_bought + n < MAX_ANIMALS_PER_TURN
            and can_afford(cost * (n + 1) + wheat_price, buffer=feed_budget)
        ):
            n += 1
        if n > 0:
            orders.append(["BUY_ANIMAL", "COW", n])
            pay(cost * n)
            animals_bought += n
            feed_need_heads += n

    # Scale sheep
    sheep_gap = sheep_target - sheep_owned
    can_buy_sheep = (
        TARGET_SHEEP > 0
        and sheep_gap > 0
        and slots_left() > 0
        and shed_sheep + inv_sheep <= 1
        and animals_bought < MAX_ANIMALS_PER_TURN
        and not cash_crunch
        and money - spent > feed_budget + 600
    )
    if can_buy_sheep:
        cost = OBJECT_TYPES["SHEEP"]["seed_cost"]
        n = 0
        while (
            n < sheep_gap
            and animals_bought + n < MAX_ANIMALS_PER_TURN
            and can_afford(cost * (n + 1) + wheat_price, buffer=feed_budget)
        ):
            n += 1
        if n > 0:
            orders.append(["BUY_ANIMAL", "SHEEP", n])
            pay(cost * n)
            animals_bought += n
            feed_need_heads += n

    # Keep herd fed via BUY_PRODUCT
    if feed_need_heads > 0 and slots_left() > 0:
        need_feed = feed_need_heads + max(2, unfed + 1)
        if day >= 8:
            need_feed = max(need_feed, n_animals + animals_bought + 4)
        if feed_wheat < need_feed:
            n = min(need_feed - feed_wheat, 8)
            while n > 0 and money - spent < wheat_price * n:
                n -= 1
            if n > 0:
                orders.append(["BUY_PRODUCT", "WHEAT", n])
                pay(wheat_price * n)
                feed_wheat += n

    # Modest wheat seeds
    if slots_left() > 0 and not cash_crunch:
        want_wheat = WHEAT_FEED_TILES
        if day >= SHORT_CYCLE_DAY:
            want_wheat = max(want_wheat, 8)
        have = int(seeds.get("WHEAT", 0) or 0) + wheat_plants
        gap = want_wheat - have
        if gap > 0:
            cost = OBJECT_TYPES["WHEAT"]["seed_cost"]
            n = min(gap, 4)
            while n > 0 and not can_afford(cost * n, buffer=feed_budget):
                n -= 1
            if n > 0:
                orders.append(["BUY_SEED", "WHEAT", n])
                pay(cost * n)

    # Early land NE / SW — never strand feed budget
    if day >= LAND_BUY_DAY and slots_left() > 0 and not cash_crunch:
        want_ne = (
            "NE" not in unlocked
            and day >= 5
            and money - spent >= 2200 + feed_budget
        )
        want_sw = (
            "SW" not in unlocked
            and "NE" in unlocked
            and day >= 12
            and money - spent >= 4500 + feed_budget
            and len(summary.get("empty") or []) < 6
        )
        if want_ne or want_sw:
            for q in LAND_ORDER:
                if q in unlocked:
                    continue
                if q == "NE" and not want_ne:
                    continue
                if q == "SW" and not want_sw:
                    continue
                extras = len(unlocked) - 1
                if 0 <= extras < len(LAND_COSTS):
                    cost = LAND_COSTS[extras]
                    if can_afford(cost, buffer=feed_budget + 200):
                        orders.append(["BUY_LAND"])
                        pay(cost)
                        unlocked.append(q)
                break

    # Top-up hires
    _add_hires(
        orders, spent, money, hands, hires_today, n_animals,
        max(n_plants, melon_target, straw_target),
        slots_left, pay, max_orders, day=day,
        pending_animals=pending_animals + animals_bought,
    )

    return orders[:max_orders]


def _day0_opening(money, seeds, hires_today, n_hands):
    """Emit the fixed 10-order Labor–Herd day-0 pack when affordable."""
    orders = []
    spent = 0.0

    # 6 HIRES
    for i in range(DAY0_HIRES):
        if n_hands + i >= DAY0_HIRES:
            break
        cost = _hire_cost(hires_today + i)
        if money - spent < cost:
            break
        orders.append(["HIRE"])
        spent += cost

    # MELON 6
    melon_have = int(seeds.get("MELON", 0) or 0)
    melon_n = max(0, DAY0_MELON_SEEDS - melon_have)
    melon_cost = OBJECT_TYPES["MELON"]["seed_cost"]
    if melon_n > 0 and money - spent >= melon_cost * melon_n and len(orders) < 10:
        orders.append(["BUY_SEED", "MELON", melon_n])
        spent += melon_cost * melon_n

    # WHEAT 12
    wheat_have = int(seeds.get("WHEAT", 0) or 0)
    wheat_n = max(0, DAY0_WHEAT_SEEDS - wheat_have)
    wheat_cost = OBJECT_TYPES["WHEAT"]["seed_cost"]
    if wheat_n > 0 and money - spent >= wheat_cost * wheat_n and len(orders) < 10:
        orders.append(["BUY_SEED", "WHEAT", wheat_n])
        spent += wheat_cost * wheat_n

    # COW 2
    cow_cost = OBJECT_TYPES["COW"]["seed_cost"] * DAY0_COWS
    if money - spent >= cow_cost and len(orders) < 10:
        orders.append(["BUY_ANIMAL", "COW", DAY0_COWS])
        spent += cow_cost

    # SHEEP 2
    sheep_cost = OBJECT_TYPES["SHEEP"]["seed_cost"] * DAY0_SHEEP
    if money - spent >= sheep_cost and len(orders) < 10:
        orders.append(["BUY_ANIMAL", "SHEEP", DAY0_SHEEP])
        spent += sheep_cost

    # Only accept if we got the core pack (hires + melon + animals)
    ops = {o[0] for o in orders}
    if "HIRE" in ops and "BUY_SEED" in ops and "BUY_ANIMAL" in ops:
        return orders[:10]
    return None


def _add_hires(orders, spent, money, hands, hires_today, n_animals, n_plants,
               slots_left, pay, max_orders, day=0, pending_animals=0):
    """Hire toward workload target; spend freely for min crew."""
    want = target_hands(n_animals + pending_animals, n_plants)
    if day == 0:
        want = max(want, DAY0_HIRES)
    elif day <= 2:
        want = max(want, 8)
    elif n_animals + pending_animals >= 8:
        want = max(want, 10)
    elif n_plants >= 8:
        want = max(want, 8)

    already = sum(1 for o in orders if o and o[0] == "HIRE")
    hires_added = 0
    spent_local = float(spent)
    min_crew = min(want, max(DAY0_HIRES if day == 0 else 4, n_animals + pending_animals + 2)) if (
        n_animals or pending_animals or n_plants or day == 0
    ) else 0

    while (
        len(hands) + already + hires_added < want
        and hires_added < MAX_HIRES_PER_TURN
        and slots_left() > 0
    ):
        cost = _hire_cost(hires_today + already + hires_added)
        need_min = len(hands) + already + hires_added < min_crew
        if need_min:
            if money - spent_local < cost:
                break
        elif money - spent_local - cost < MIN_CASH_BUFFER:
            break
        orders.append(["HIRE"])
        pay(cost)
        spent_local += cost
        hires_added += 1
