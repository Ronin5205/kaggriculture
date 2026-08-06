"""Market-order policy for the meta farms agent."""

from .constants import (
    META_TARGETS,
    EARLY_SEED_TARGETS,
    SELL_BATCH,
    SELL_PRICE_FLOOR_FRAC,
    LAND_BUY_DAY,
    LAND_COSTS,
    OBJECT_TYPES,
    MARKET_PARAMS,
    FIBONACCI_HIRE_SEQUENCE,
    PRICE_FLOOR,
)

MAX_HIRES_PER_TURN = 4
MAX_ANIMALS_PER_TURN = 2
# Keep enough cash for feed + a land payment buffer once expanding.
MIN_CASH_BUFFER = 150


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


def _should_sell(item, price):
    if price is None:
        return False
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
    day = obs.get("day", 0)
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
    shed_cows = int(shed.get("COW", 0) or 0)
    shed_sheep = int(shed.get("SHEEP", 0) or 0)
    inv_cows = _count_in_inv(inventories, "COW")
    inv_sheep = _count_in_inv(inventories, "SHEEP")
    n_animals = n_cows + n_sheep
    unfed = len(summary.get("unfed_animals") or [])

    cows_owned = n_cows + shed_cows + inv_cows
    sheep_owned = n_sheep + shed_sheep + inv_sheep
    pending_animals = shed_cows + shed_sheep + inv_cows + inv_sheep

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
    # Animals we will owe feed to (placed + about to place).
    feed_need_heads = n_animals + pending_animals

    # --- 1. Always secure feed before anything else ---
    # Need at least 1 wheat per live/pending animal for today, plus a small stockpile.
    feed_target = max(feed_need_heads + 2, unfed + 2) if feed_need_heads or unfed else 0
    # Avoid staging huge feed buys before animals exist; 6 is enough to start.
    if cows_owned + sheep_owned == 0 and day < 3:
        feed_target = max(feed_target, 6)
    elif feed_need_heads > 0:
        feed_target = max(feed_target, min(feed_need_heads + 3, feed_need_heads + 6))

    # Don't keep buying wheat every turn once stocked — burns cash.
    if feed_target > feed_wheat and slots_left() > 0:
        n = min(feed_target - feed_wheat, 8)
        while n > 0 and money - spent < wheat_price * n:
            n -= 1
        if n > 0:
            orders.append(["BUY_PRODUCT", "WHEAT", n])
            pay(wheat_price * n)
            feed_wheat += n

    # --- 2. Buy animals gradually ---
    animals_bought = 0
    for animal, owned, target in (
        ("COW", cows_owned, META_TARGETS["COW"]),
        ("SHEEP", sheep_owned, META_TARGETS["SHEEP"]),
    ):
        gap = target - owned
        if gap <= 0 or slots_left() <= 0 or animals_bought >= MAX_ANIMALS_PER_TURN:
            continue
        cost = OBJECT_TYPES[animal]["seed_cost"]
        # Only buy if we can also afford tomorrow's feed for the new head.
        n = 0
        while (
            n < gap
            and animals_bought + n < MAX_ANIMALS_PER_TURN
            and can_afford(cost * (n + 1) + wheat_price)
        ):
            n += 1
        if n > 0:
            orders.append(["BUY_ANIMAL", animal, n])
            pay(cost * n)
            animals_bought += n
            feed_need_heads += n

    # Top up feed again if we just bought animals.
    if feed_wheat < feed_need_heads + 2 and slots_left() > 0 and feed_need_heads > 0:
        n = min(feed_need_heads + 2 - feed_wheat, 8)
        while n > 0 and money - spent < wheat_price * n:
            n -= 1
        if n > 0:
            orders.append(["BUY_PRODUCT", "WHEAT", n])
            pay(wheat_price * n)
            feed_wheat += n

    # --- 3. Seeds (modest early buys) ---
    straw_count = crop_counts.get("STRAWBERRY", 0)
    wheat_plants = crop_counts.get("WHEAT", 0)
    melon_plants = crop_counts.get("MELON", 0)

    if day < 12 and slots_left() > 0:
        want = min(EARLY_SEED_TARGETS["MELON"], 4) if day < 5 else 1
        have = seeds.get("MELON", 0) + melon_plants
        gap = want - have
        if gap > 0:
            cost = OBJECT_TYPES["MELON"]["seed_cost"]
            n = min(gap, 2)
            while n > 0 and not can_afford(cost * n):
                n -= 1
            if n > 0:
                orders.append(["BUY_SEED", "MELON", n])
                pay(cost * n)

    if slots_left() > 0:
        want = META_TARGETS["STRAWBERRY"]
        if day < 5:
            want = min(want, 2)
        have = seeds.get("STRAWBERRY", 0) + straw_count
        gap = want - have
        if gap > 0 and (day >= 3 or money - spent > 800):
            cost = OBJECT_TYPES["STRAWBERRY"]["seed_cost"]
            n = min(gap, 2)
            while n > 0 and not can_afford(cost * n):
                n -= 1
            if n > 0:
                orders.append(["BUY_SEED", "STRAWBERRY", n])
                pay(cost * n)

    if slots_left() > 0:
        # Grow our own feed tile + a few early wheat harvests.
        want_seeds = 4 if day < 5 else max(0, META_TARGETS["WHEAT"] - wheat_plants)
        have = seeds.get("WHEAT", 0)
        gap = want_seeds - have if day < 5 else max(0, META_TARGETS["WHEAT"] - wheat_plants - have)
        if gap > 0:
            cost = OBJECT_TYPES["WHEAT"]["seed_cost"]
            n = min(gap, 4)
            while n > 0 and not can_afford(cost * n):
                n -= 1
            if n > 0:
                orders.append(["BUY_SEED", "WHEAT", n])
                pay(cost * n)

    # --- 4. Land ---
    target_land = set(META_TARGETS["LAND"])
    if day >= LAND_BUY_DAY and slots_left() > 0:
        for q in ("NE", "SW"):
            if q in unlocked or q not in target_land:
                continue
            extras = len(unlocked) - 1
            if 0 <= extras < len(LAND_COSTS):
                cost = LAND_COSTS[extras]
                if can_afford(cost, buffer=300):
                    orders.append(["BUY_LAND"])
                    pay(cost)
            break

    # --- 5. Metered sells ---
    sell_priority = [
        "FERTILIZER", "MILK", "WOOL", "MELON", "STRAWBERRY", "WHEAT",
        "EGG", "TOMATO", "CARROT",
    ]
    wheat_reserve = max(feed_need_heads + 4, unfed + 4, 6 if n_animals else 0)

    for item in sell_priority:
        if slots_left() <= 0:
            break
        qty = int(shed.get(item, 0) or 0)
        if item == "WHEAT":
            # Never sell wheat while any animals are alive or pending.
            if feed_need_heads > 0 or n_animals > 0:
                continue
            qty = max(0, qty - wheat_reserve)
        if qty <= 0:
            continue
        price = prices.get(item)
        if not _should_sell(item, price):
            continue
        batch = min(SELL_BATCH.get(item, 4), qty)
        if batch > 0:
            orders.append(["SELL", item, batch])
            shed[item] = qty - batch

    # --- 6. Hire (keep a crew for feeding even when cash is tight) ---
    hires_added = 0
    min_hands = 6 if (feed_need_heads or n_animals) else 0
    target_hands = META_TARGETS["HANDS"]
    while (
        len(hands) + hires_added < target_hands
        and hires_added < MAX_HIRES_PER_TURN
        and slots_left() > 0
    ):
        cost = _hire_cost(hires_today + hires_added)
        need_min = len(hands) + hires_added < min_hands
        # Minimum crew: spend down to 0. Extra hands: keep a cash buffer.
        if need_min:
            if money - spent < cost:
                break
        elif money - spent - cost < MIN_CASH_BUFFER:
            break
        orders.append(["HIRE"])
        pay(cost)
        hires_added += 1

    return orders[:max_orders]
