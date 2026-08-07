"""Market-order policy — Seb-timed Labor–Herd (user day-0 pack).

Mined from episode 90503598:
  morning mass HIRE, drip BUY_PRODUCT WHEAT, aggressive FERTILIZER sells,
  NE land ~d4, strawberry burst d5, SW land ~d6, herd scale d9–d13.
Day-0 pack kept as user-specified 10-order fit.
"""

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
    TARGET_HANDS_MAX,
    target_hands,
)

MAX_ANIMALS_PER_TURN = 2
MIN_CASH_BUFFER = 40


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
    # Fertilizer: Seb sells almost any day
    if item == "FERTILIZER":
        return float(price) >= 10
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
    if day <= 10:
        return 5
    if day <= 13:
        return 9
    return TARGET_SHEEP


def _cow_target(day):
    if day <= 3:
        return 2
    if day <= 5:
        return 4
    if day <= 9:
        return 5
    if day <= 11:
        return 8
    return TARGET_COWS


def _strawberry_buy_target(day, melon_plants):
    if day < 5 or day > NO_LONG_CROP_AFTER_DAY:
        return 0
    if day == 5:
        return 11  # Seb burst
    if day <= 7:
        return 22
    if day <= 9:
        return 33
    if day <= 12:
        return STRAWBERRY_TARGET
    return STRAWBERRY_TARGET


def _melon_buy_target(day):
    if day == 0:
        return DAY0_MELON_SEEDS
    if day <= 4:
        return MELON_WAVE1
    if day <= 8:
        return 14
    if day <= WAVE2_END_DAY and day <= NO_LONG_CROP_AFTER_DAY:
        return MELON_WAVE2
    return 0


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

    cow_target = _cow_target(day)
    sheep_target = _sheep_target(day)
    melon_target = _melon_buy_target(day)
    straw_target = _strawberry_buy_target(day, melon_plants)

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

    # --- Day-0 pack (user): 6 HIRE + MELON6 + WHEAT12 + COW2 + SHEEP2 ---
    if (
        day == 0
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
    feed_target = max(feed_need_heads + 1, unfed + 1) if (feed_need_heads or unfed) else 0
    wheat_reserve = max(feed_target, feed_need_heads)
    if force_floor:
        wheat_reserve = unfed
    allow_wheat_sell = (
        in_cashout
        or day >= SHORT_CYCLE_DAY
        or (day >= 4 and wheat_plants + int(seeds.get("WHEAT", 0) or 0) >= 8)
        or money < 100
    )
    cash_crunch = money < max(200, feed_need_heads * wheat_price) or unfed > 0

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
            # Seb often sells fert in small batches, milk/wool in 4–6
            if item == "FERTILIZER":
                batch = min(max(1, batch), qty, 10)
            if force:
                batch = min(max(batch, 1), qty)
            if batch > 0:
                orders.append(["SELL", item, batch])
                shed[item] = qty - batch
                pay(-float(price or 0) * batch)

    # Morning: sell fert/milk then hire (Seb pattern hour 1)
    emit_sells(aggressive=in_cashout or cash_crunch or hour <= 2)

    if in_cashout:
        _morning_hires(orders, spent, money, hands, hires_today, n_animals, n_plants,
                       slots_left, pay, day, pending_animals)
        emit_sells(aggressive=True)
        return orders[:max_orders]

    # Critical feed drip (Seb buys 1–2 wheat product repeatedly)
    if feed_wheat < max(unfed + 1, feed_need_heads) and slots_left() > 0:
        need = max(unfed + 1, feed_need_heads) - feed_wheat
        n = min(need, 3)
        while n > 0 and money - spent < wheat_price * n:
            n -= 1
        if n > 0:
            orders.append(["BUY_PRODUCT", "WHEAT", n])
            pay(wheat_price * n)
            feed_wheat += n

    # Morning mass hire toward 7–12 hands
    _morning_hires(orders, spent, money, hands, hires_today, n_animals, n_plants,
                   slots_left, pay, day, pending_animals)

    feed_budget = feed_need_heads * wheat_price + 80

    # Land NE ~day 4, SW ~day 6–7, SE ~day 10 (Seb)
    if slots_left() > 0 and not cash_crunch:
        if "NE" not in unlocked and day >= LAND_BUY_DAY and money - spent >= 1000 + feed_budget:
            if can_afford(LAND_COSTS[0], buffer=feed_budget):
                orders.append(["BUY_LAND"])
                pay(LAND_COSTS[0])
                unlocked.append("NE")
        elif (
            "SW" not in unlocked
            and "NE" in unlocked
            and day >= 6
            and money - spent >= 2000 + feed_budget
        ):
            if can_afford(LAND_COSTS[1], buffer=feed_budget):
                orders.append(["BUY_LAND"])
                pay(LAND_COSTS[1])
                unlocked.append("SW")
        elif (
            "SE" not in unlocked
            and "SW" in unlocked
            and day >= 10
            and money - spent >= 4500 + feed_budget
        ):
            if can_afford(LAND_COSTS[2], buffer=feed_budget):
                orders.append(["BUY_LAND"])
                pay(LAND_COSTS[2])
                unlocked.append("SE")

    # Strawberry burst day 5+
    if straw_target > 0 and slots_left() > 0 and money - spent > feed_budget + 200:
        have = int(seeds.get("STRAWBERRY", 0) or 0) + straw_plants
        gap = straw_target - have
        if gap > 0:
            cost = OBJECT_TYPES["STRAWBERRY"]["seed_cost"]
            n = min(gap, 11 if day == 5 else 6)
            while n > 0 and not can_afford(cost * n, buffer=feed_budget):
                n -= 1
            if n > 0:
                orders.append(["BUY_SEED", "STRAWBERRY", n])
                pay(cost * n)

    # Melon top-ups after day 0
    if day > 0 and melon_target > 0 and slots_left() > 0 and money - spent > feed_budget + 150:
        have = int(seeds.get("MELON", 0) or 0) + melon_plants
        gap = melon_target - have
        if gap > 0:
            cost = OBJECT_TYPES["MELON"]["seed_cost"]
            n = min(gap, 4)
            while n > 0 and not can_afford(cost * n, buffer=feed_budget):
                n -= 1
            if n > 0:
                orders.append(["BUY_SEED", "MELON", n])
                pay(cost * n)

    # Animals — Seb adds cows early, sheep after d9
    animals_bought = 0
    if (
        cows_owned < cow_target
        and shed_cows + inv_cows <= 1
        and slots_left() > 0
        and money - spent > feed_budget + 400
        and not cash_crunch
    ):
        cost = OBJECT_TYPES["COW"]["seed_cost"]
        n = 0
        gap = cow_target - cows_owned
        while n < gap and animals_bought + n < MAX_ANIMALS_PER_TURN and can_afford(
            cost * (n + 1) + wheat_price, buffer=feed_budget
        ):
            n += 1
        if n > 0:
            orders.append(["BUY_ANIMAL", "COW", n])
            pay(cost * n)
            animals_bought += n
            feed_need_heads += n

    if (
        sheep_owned < sheep_target
        and shed_sheep + inv_sheep <= 1
        and slots_left() > 0
        and animals_bought < MAX_ANIMALS_PER_TURN
        and money - spent > feed_budget + 500
        and not cash_crunch
    ):
        cost = OBJECT_TYPES["SHEEP"]["seed_cost"]
        n = 0
        gap = sheep_target - sheep_owned
        while n < gap and animals_bought + n < MAX_ANIMALS_PER_TURN and can_afford(
            cost * (n + 1) + wheat_price, buffer=feed_budget
        ):
            n += 1
        if n > 0:
            orders.append(["BUY_ANIMAL", "SHEEP", n])
            pay(cost * n)
            animals_bought += n
            feed_need_heads += n

    # Feed drip top-up
    if feed_need_heads > feed_wheat and slots_left() > 0:
        n = min(feed_need_heads - feed_wheat + 1, 4)
        while n > 0 and money - spent < wheat_price * n:
            n -= 1
        if n > 0:
            orders.append(["BUY_PRODUCT", "WHEAT", n])
            pay(wheat_price * n)

    # Modest wheat seeds (Seb buys small top-ups, not 90 plants)
    if slots_left() > 0 and day > 0 and money - spent > feed_budget:
        want = WHEAT_FEED_TILES if day < SHORT_CYCLE_DAY else 4
        have = int(seeds.get("WHEAT", 0) or 0) + wheat_plants
        gap = want - have
        if gap > 0:
            cost = OBJECT_TYPES["WHEAT"]["seed_cost"]
            n = min(gap, 2)
            if can_afford(cost * n, buffer=feed_budget):
                orders.append(["BUY_SEED", "WHEAT", n])
                pay(cost * n)

    # Late sells again if slots remain
    if slots_left() > 0 and hour >= 12:
        emit_sells(aggressive=False)

    return orders[:max_orders]


def _day0_opening(money, seeds, hires_today, n_hands):
    orders = []
    spent = 0.0
    for i in range(DAY0_HIRES):
        if n_hands + i >= DAY0_HIRES:
            break
        cost = _hire_cost(hires_today + i)
        if money - spent < cost:
            break
        orders.append(["HIRE"])
        spent += cost

    melon_n = max(0, DAY0_MELON_SEEDS - int(seeds.get("MELON", 0) or 0))
    melon_cost = OBJECT_TYPES["MELON"]["seed_cost"]
    if melon_n > 0 and money - spent >= melon_cost * melon_n and len(orders) < 10:
        orders.append(["BUY_SEED", "MELON", melon_n])
        spent += melon_cost * melon_n

    wheat_n = max(0, DAY0_WHEAT_SEEDS - int(seeds.get("WHEAT", 0) or 0))
    wheat_cost = OBJECT_TYPES["WHEAT"]["seed_cost"]
    if wheat_n > 0 and money - spent >= wheat_cost * wheat_n and len(orders) < 10:
        orders.append(["BUY_SEED", "WHEAT", wheat_n])
        spent += wheat_cost * wheat_n

    cow_cost = OBJECT_TYPES["COW"]["seed_cost"] * DAY0_COWS
    if money - spent >= cow_cost and len(orders) < 10:
        orders.append(["BUY_ANIMAL", "COW", DAY0_COWS])
        spent += cow_cost

    sheep_cost = OBJECT_TYPES["SHEEP"]["seed_cost"] * DAY0_SHEEP
    if money - spent >= sheep_cost and len(orders) < 10:
        orders.append(["BUY_ANIMAL", "SHEEP", DAY0_SHEEP])
        spent += sheep_cost

    ops = {o[0] for o in orders}
    if "HIRE" in ops and "BUY_SEED" in ops and "BUY_ANIMAL" in ops:
        return orders[:10]
    return None


def _morning_hires(orders, spent, money, hands, hires_today, n_animals, n_plants,
                   slots_left, pay, day, pending_animals=0):
    """Seb hires 7–12 every morning."""
    want = target_hands(n_animals + pending_animals, n_plants)
    if day <= 1:
        want = max(want, 7)
    elif day <= 8:
        want = max(want, 8)
    else:
        want = max(want, min(TARGET_HANDS_MAX, 10 + (n_animals // 4)))

    already = sum(1 for o in orders if o and o[0] == "HIRE")
    hires_added = 0
    spent_local = float(spent)
    while (
        len(hands) + already + hires_added < want
        and hires_added < MAX_HIRES_PER_TURN
        and slots_left() > 0
    ):
        cost = _hire_cost(hires_today + already + hires_added)
        if money - spent_local < cost:
            break
        # Keep a little feed cash after first 7 hires
        if len(hands) + already + hires_added >= 7 and money - spent_local - cost < 30:
            break
        orders.append(["HIRE"])
        pay(cost)
        spent_local += cost
        hires_added += 1
