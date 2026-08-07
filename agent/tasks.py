"""Priority tile jobs — hardcoded Seb-layout Labor–Herd strategy."""

from .constants import (
    MELON_WAVE1,
    MELON_WAVE2,
    TARGET_COWS,
    TARGET_SHEEP,
    WHEAT_FEED_TILES,
    STRAWBERRY_WAVE1,
    STRAWBERRY_TARGET,
    WAVE1_END_DAY,
    NO_LONG_CROP_AFTER_DAY,
    SHORT_CYCLE_DAY,
    CASHOUT_DAY,
    OBJECT_TYPES,
)
from .layout import (
    PASTURE_SLOTS,
    MELON_SLOTS,
    WHEAT_SLOTS,
    STRAWBERRY_SLOTS,
    next_slots,
)
from .pathing import (
    is_shed_adjacent,
    nearest_shed_tile,
    nearest_pos,
    step_toward,
    manhattan,
)
from .state_tile import plant_needs_water

# Seb chore order: feed/place/build → care → water(needed) → harvest → plant
PRIO_FEED = 10
PRIO_PLACE = 11
PRIO_BUILD = 12
PRIO_CARE = 13
PRIO_WATER_MELON = 14
PRIO_WATER = 15
PRIO_HARVEST = 16
PRIO_PLANT_MELON = 17
PRIO_PLANT_WHEAT = 18
PRIO_PLANT_STRAW = 19
PRIO_FERT_COLLECT = 30
PRIO_FERTILIZE = 40
PRIO_DIG = 50
PRIO_PLANT = 90


def _inv_count(inv, item):
    if not isinstance(inv, dict):
        return 0
    return inv.get(item, 0)


def _inv_total(inv):
    if not isinstance(inv, dict):
        return 0
    return sum(inv.values())


def _tile_at(farm, pos):
    x, y = pos
    return farm["tiles"][y][x]


def _melon_target(day):
    if day <= 4:
        return MELON_WAVE1
    if day <= WAVE1_END_DAY:
        return max(MELON_WAVE1, 9)
    if day <= NO_LONG_CROP_AFTER_DAY:
        return MELON_WAVE2
    return 0


def _sheep_target(day):
    # Seb: 2 day0, +cows early, sheep scale after d9
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


def _strawberry_want(day, melon_now):
    if day < 5 or day > NO_LONG_CROP_AFTER_DAY:
        return 0
    if day <= 6:
        return STRAWBERRY_WAVE1
    if day <= 9:
        return 24
    if day <= 12:
        return 40
    return STRAWBERRY_TARGET


def build_tasks(obs, summary, claimed):
    player = obs.get("player", 0)
    me = obs["farms"][player]
    private = obs.get("private") or {}
    day = int(obs.get("day", 0) or 0)
    shed = private.get("shed") or {}
    seeds = private.get("seeds") or {}
    farm = me
    tiles = farm["tiles"]

    crop_counts = summary.get("crop_counts") or {}
    animal_counts = summary.get("animal_counts") or {}
    n_pastures = len(summary.get("pastures") or [])
    n_cows = animal_counts.get("COW", 0)
    n_sheep = animal_counts.get("SHEEP", 0)

    owned = (
        n_cows + n_sheep
        + int(shed.get("COW", 0) or 0)
        + int(shed.get("SHEEP", 0) or 0)
    )
    melon_now = crop_counts.get("MELON", 0)
    straw_now = crop_counts.get("STRAWBERRY", 0)
    cow_target = _cow_target(day)
    sheep_target = _sheep_target(day)
    herd_target = min(cow_target + sheep_target, max(owned, 1) if owned else 0)

    # House every owned animal; Seb builds ~8 pastures day0 but we interleave
    # with planting — start with enough for opener animals + a few spare.
    if day == 0:
        pasture_target = max(4, owned + 2)
    else:
        pasture_target = max(owned, min(cow_target + sheep_target, owned + 1)) if owned else 0
    pasture_gap = max(0, pasture_target - n_pastures)

    empty = [p for p in summary.get("empty") or [] if p not in claimed]
    tasks = []

    def add(prio, pos, act, item=None):
        if pos is None or pos in claimed:
            return
        t = {"prio": prio, "pos": pos, "act": act}
        if item is not None:
            t["item"] = item
        tasks.append(t)

    # Day 0: plant opener seeds BEFORE finishing all pastures (Seb interleaves).
    early = day == 0 and (melon_now < MELON_WAVE1 or int(seeds.get("WHEAT", 0) or 0) > 0)
    build_prio = PRIO_BUILD + (4 if early else 0)
    place_prio = PRIO_PLACE + (4 if early else 0)
    plant_melon_prio = 11 if early else PRIO_PLANT_MELON
    plant_wheat_prio = 12 if early else PRIO_PLANT_WHEAT

    # --- Animals first (Seb never lets feed/care slip) ---
    for pos in summary.get("unfed_animals") or []:
        add(PRIO_FEED, pos, "FEED")
    for pos in summary.get("uncared_animals") or []:
        add(PRIO_CARE, pos, "CARE")

    # --- Water only tiles that NEED it (survival or growth window) ---
    plant_by_pos = {(x, y): crop for x, y, crop in summary.get("plants") or []}
    need_water = summary.get("needs_water_plants") or summary.get("unwatered_plants") or []
    for pos in need_water:
        crop = plant_by_pos.get(pos)
        if crop == "MELON":
            add(PRIO_WATER_MELON, pos, "WATER")
        else:
            add(PRIO_WATER, pos, "WATER")

    for pos in summary.get("harvestable_animals") or []:
        add(PRIO_HARVEST, pos, "HARVEST")

    for pos in summary.get("harvestable_plants") or []:
        x, y = pos
        tile = tiles[y][x]
        if not tile or tile == "LOCKED":
            continue
        try:
            if tile["kind"] != "PLANT":
                continue
            crop = tile["crop"]
            planted = tile["planted_day"]
        except (TypeError, KeyError, IndexError):
            continue
        age = day - int(planted if planted is not None else day)
        meta = OBJECT_TYPES.get(crop) or {}
        if meta.get("yield_type") == "ONE_TIME":
            if crop == "MELON":
                ready_day = int(meta.get("time_to_max_yield_days") or 10)
            else:
                ready_day = int(meta.get("time_to_first_yield_days") or 2)
            if age < ready_day:
                continue
        add(PRIO_HARVEST, pos, "HARVEST")

    for pos in summary.get("collectible_fertilizer") or []:
        add(PRIO_FERT_COLLECT, pos, "COLLECT_FERTILIZER")

    fert_avail = int(shed.get("FERTILIZER", 0) or 0)
    for crop_name in ("MELON", "STRAWBERRY", "WHEAT"):
        if fert_avail <= 0:
            break
        for x, y, crop in summary.get("plants") or []:
            if crop != crop_name:
                continue
            tile = tiles[y][x]
            if not isinstance(tile, dict):
                continue
            if tile.get("fertilized_until_day", -1) >= day:
                continue
            if fert_avail <= 0:
                break
            add(PRIO_FERTILIZE, (x, y), "FERTILIZE")
            fert_avail -= 1

    for pos in summary.get("weeds") or []:
        # Weeds explode if ignored — clear before optional planting midgame
        dig_p = 16 if len(summary.get("weeds") or []) >= 5 else PRIO_DIG
        add(dig_p, pos, "DIG")

    # Pastures: Seb builds 8 on day0 but AFTER some plants start — cap while planting
    build_n = pasture_gap
    if early:
        build_n = min(pasture_gap, max(2, owned + 2))
    if build_n > 0:
        for pos in next_slots(PASTURE_SLOTS, empty, claimed, limit=build_n):
            add(build_prio, pos, "BUILD_PASTURE")

    empty_structs = [
        p for p in summary.get("structures_empty") or [] if p not in claimed
    ]
    empty_structs.sort(
        key=lambda p: PASTURE_SLOTS.index(p) if p in PASTURE_SLOTS else 999
    )
    cow_gap = cow_target - n_cows
    sheep_gap = sheep_target - n_sheep
    shed_cows = int(shed.get("COW", 0) or 0)
    shed_sheep = int(shed.get("SHEEP", 0) or 0)
    for pos in empty_structs:
        tile = _tile_at(farm, pos)
        if not isinstance(tile, dict) or tile.get("kind") != "PASTURE":
            continue
        if day == 0 and (sheep_gap > 0 or shed_sheep > 0):
            add(place_prio, pos, "PLACE", "SHEEP")
            sheep_gap -= 1
            shed_sheep = max(0, shed_sheep - 1)
        elif cow_gap > 0 or shed_cows > 0:
            add(place_prio, pos, "PLACE", "COW")
            cow_gap -= 1
            shed_cows = max(0, shed_cows - 1)
        elif sheep_gap > 0 or shed_sheep > 0:
            add(place_prio, pos, "PLACE", "SHEEP")
            sheep_gap -= 1
            shed_sheep = max(0, shed_sheep - 1)

    melon = melon_now
    melon_want = _melon_target(day)
    straw = straw_now
    straw_want = _strawberry_want(day, melon_now)
    wheat = crop_counts.get("WHEAT", 0)
    seed_left = {
        "WHEAT": int(seeds.get("WHEAT", 0) or 0),
        "MELON": int(seeds.get("MELON", 0) or 0),
        "STRAWBERRY": int(seeds.get("STRAWBERRY", 0) or 0),
    }

    want_wheat = WHEAT_FEED_TILES
    if day == 0:
        want_wheat = max(want_wheat, min(14, seed_left["WHEAT"]))
    elif day <= 5:
        want_wheat = max(want_wheat, min(4, seed_left["WHEAT"] + wheat))
    if day >= SHORT_CYCLE_DAY:
        want_wheat = max(want_wheat, 4)

    labor = 1 + len(me.get("hands") or [])
    n_need_water = len(need_water)
    n_unfed = len(summary.get("unfed_animals") or [])
    n_uncared = len(summary.get("uncared_animals") or [])
    if day == 0:
        max_new_plants = 99
    else:
        reserved = n_unfed + n_uncared + min(n_need_water, max(labor // 2, 0))
        max_new_plants = max(4, labor - reserved)
    plants_added = 0

    plant_plan = []
    if day <= NO_LONG_CROP_AFTER_DAY:
        for pos in next_slots(MELON_SLOTS, empty, claimed, limit=99):
            if melon >= melon_want or seed_left["MELON"] <= 0:
                break
            plant_plan.append((plant_melon_prio, pos, "MELON"))
            melon += 1
            seed_left["MELON"] -= 1
    for pos in next_slots(WHEAT_SLOTS, empty, claimed, limit=99):
        if wheat >= want_wheat or seed_left["WHEAT"] <= 0:
            break
        if any(p == pos for _, p, _ in plant_plan):
            continue
        plant_plan.append((plant_wheat_prio, pos, "WHEAT"))
        wheat += 1
        seed_left["WHEAT"] -= 1
    if straw_want > 0:
        for pos in next_slots(STRAWBERRY_SLOTS, empty, claimed, limit=99):
            if straw >= straw_want or seed_left["STRAWBERRY"] <= 0:
                break
            if any(p == pos for _, p, _ in plant_plan):
                continue
            plant_plan.append((PRIO_PLANT_STRAW, pos, "STRAWBERRY"))
            straw += 1
            seed_left["STRAWBERRY"] -= 1

    for prio, pos, crop in plant_plan:
        if plants_added >= max_new_plants:
            break
        plants_added += 1
        add(prio, pos, "PLANT", crop)

    return tasks


def _needed_pickup(task, inv, shed):
    act = task["act"]
    if act == "FEED":
        if _inv_count(inv, "WHEAT") < 1 and shed.get("WHEAT", 0) > 0:
            return "WHEAT", min(8, int(shed.get("WHEAT", 0)))
    if act == "FERTILIZE":
        if _inv_count(inv, "FERTILIZER") < 1 and shed.get("FERTILIZER", 0) > 0:
            return "FERTILIZER", 1
    if act == "PLACE":
        animal = task.get("item")
        if animal and _inv_count(inv, animal) < 1 and shed.get(animal, 0) > 0:
            return animal, 1
    return None


def assign_unit_action(pos, inv, obs, summary, tasks, claimed):
    player = obs.get("player", 0)
    me = obs["farms"][player]
    private = obs.get("private") or {}
    day = int(obs.get("day", 0) or 0)
    shed = private.get("shed") or {}
    board_size = len(me["tiles"])
    tiles = me["tiles"]
    unfed = [p for p in (summary.get("unfed_animals") or []) if p not in claimed]
    empty_pastures = [
        p for p in (summary.get("structures_empty") or []) if p not in claimed
    ]
    n_animals = sum((summary.get("animal_counts") or {}).values())
    in_cashout = day >= CASHOUT_DAY

    carrying_cow = _inv_count(inv, "COW")
    carrying_sheep = _inv_count(inv, "SHEEP")
    carrying_animal = "COW" if carrying_cow else ("SHEEP" if carrying_sheep else None)

    if carrying_animal and empty_pastures:
        # Prefer Seb pasture order
        empty_pastures = sorted(
            empty_pastures,
            key=lambda p: PASTURE_SLOTS.index(p) if p in PASTURE_SLOTS else 999,
        )
        target = empty_pastures[0]
        claimed.add(target)
        if pos == target:
            return ["PLACE", carrying_animal]
        return list(step_toward(pos, target, board_size))

    if unfed and _inv_count(inv, "WHEAT") < 1 and shed.get("WHEAT", 0) > 0:
        if is_shed_adjacent(pos):
            return ["PICKUP", "WHEAT", min(8, int(shed.get("WHEAT", 0)))]
        return list(step_toward(pos, nearest_shed_tile(pos), board_size))

    if unfed and _inv_count(inv, "WHEAT") >= 1:
        target = nearest_pos(pos, unfed)
        if target is not None:
            claimed.add(target)
            if pos == target:
                return ["FEED"]
            return list(step_toward(pos, target, board_size))

    if not carrying_animal and is_shed_adjacent(pos):
        produce_keys = (
            "MELON", "STRAWBERRY", "MILK", "WOOL", "FERTILIZER",
            "EGG", "TOMATO", "CARROT",
        )
        if any(_inv_count(inv, k) > 0 for k in produce_keys):
            return ["DROP"]
        if _inv_count(inv, "WHEAT") > 0 and not unfed and (
            in_cashout or _inv_count(inv, "WHEAT") > 3
        ):
            return ["DROP"]

    if not carrying_animal and any(
        _inv_count(inv, k) > 0
        for k in ("MELON", "MILK", "WOOL", "FERTILIZER", "STRAWBERRY")
    ):
        if not is_shed_adjacent(pos):
            return list(step_toward(pos, nearest_shed_tile(pos), board_size))

    if (
        not carrying_animal
        and _inv_total(inv) >= 3
        and not is_shed_adjacent(pos)
        and not (unfed and _inv_count(inv, "WHEAT") > 0)
    ):
        return list(step_toward(pos, nearest_shed_tile(pos), board_size))

    available = [t for t in tasks if t["pos"] not in claimed]
    available.sort(key=lambda t: (t["prio"], manhattan(pos, t["pos"])))

    for task in available:
        need = _needed_pickup(task, inv, shed)
        if need:
            item, n = need
            if is_shed_adjacent(pos):
                return ["PICKUP", item, n]
            return list(step_toward(pos, nearest_shed_tile(pos), board_size))

        if task["act"] == "PLACE" and _inv_count(inv, task.get("item")) < 1:
            continue
        if task["act"] == "FEED" and _inv_count(inv, "WHEAT") < 1:
            continue
        if task["act"] == "FERTILIZE" and _inv_count(inv, "FERTILIZER") < 1:
            continue

        # Re-check water need on arrival — avoid watering already-safe tiles
        if task["act"] == "WATER" and pos == task["pos"]:
            tile = tiles[task["pos"][1]][task["pos"][0]]
            if isinstance(tile, dict) and not plant_needs_water(tile, day):
                claimed.add(task["pos"])
                continue

        claimed.add(task["pos"])
        if pos == task["pos"]:
            if task["act"] == "PLANT":
                return ["PLANT", task["item"]]
            if task["act"] == "PLACE":
                return ["PLACE", task["item"]]
            return [task["act"]]
        return list(step_toward(pos, task["pos"], board_size))

    if is_shed_adjacent(pos) and not carrying_animal:
        for animal in ("SHEEP", "COW"):
            if empty_pastures and shed.get(animal, 0) > 0:
                return ["PICKUP", animal, 1]
        if (unfed or n_animals) and shed.get("WHEAT", 0) > 0 and _inv_count(inv, "WHEAT") < 3:
            return ["PICKUP", "WHEAT", min(5, int(shed.get("WHEAT", 0)))]

    if empty_pastures and (shed.get("COW", 0) or shed.get("SHEEP", 0)) and not carrying_animal:
        return list(step_toward(pos, nearest_shed_tile(pos), board_size))

    if in_cashout and _inv_total(inv) > 0 and not is_shed_adjacent(pos):
        return list(step_toward(pos, nearest_shed_tile(pos), board_size))

    # Seb idles with PASS near shed once chores done
    if not is_shed_adjacent(pos):
        return list(step_toward(pos, nearest_shed_tile(pos), board_size))
    return ["PASS"]
