"""Priority tile jobs — Labor–Herd Compound strategy."""

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
from .pathing import (
    is_shed_adjacent,
    nearest_shed_tile,
    nearest_pos,
    step_toward,
    pasture_empties,
    plantable_empties,
    manhattan,
    sort_by_shed_near,
)

# Lower = sooner.
PRIO_FEED = 10
PRIO_PLACE = 11
PRIO_BUILD = 12
PRIO_PLANT_MELON = 13
PRIO_CARE = 14
PRIO_WATER_MELON = 15
PRIO_HARVEST = 16
PRIO_WATER = 18
PRIO_PLANT_STRAW = 22
PRIO_DIG = 28
PRIO_FERT_COLLECT = 35
PRIO_FERTILIZE = 55
PRIO_PLANT = 100


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
    if day <= WAVE1_END_DAY:
        return MELON_WAVE1
    if day <= NO_LONG_CROP_AFTER_DAY:
        return MELON_WAVE2
    return 0


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


def _strawberry_want(day, melon_now):
    if day > NO_LONG_CROP_AFTER_DAY:
        return 0
    if day <= 3:
        return 0
    if day <= WAVE1_END_DAY:
        if melon_now >= MELON_WAVE1 - 1:
            return STRAWBERRY_WAVE1
        return 0
    if day <= 16:
        return 24
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
    herd_target = cow_target + sheep_target
    wave1_rush = melon_now < MELON_WAVE1 and day <= WAVE1_END_DAY

    # House the whole owned herd ASAP (animals escape if unplaced/unfed).
    if owned > 0:
        pasture_target = max(owned, min(herd_target, owned + 1))
    else:
        pasture_target = 0
    if day > 0 and owned >= 2:
        pasture_target = max(pasture_target, min(herd_target, owned + 1))
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

    seeds_waiting = int(seeds.get("MELON", 0) or 0) > 0 and melon_now < _melon_target(day)
    straw_waiting = int(seeds.get("STRAWBERRY", 0) or 0) > 0
    # Early: plant opener seeds before housing animals (shed is safe).
    early_plant = day <= 2 and (melon_now < MELON_WAVE1 or int(seeds.get("WHEAT", 0) or 0) > 0)
    plant_prio = 11 if early_plant else (PRIO_PLANT_MELON if (wave1_rush or seeds_waiting) else PRIO_PLANT_MELON + 3)
    care_prio = 12 if owned >= 6 else PRIO_CARE
    build_prio = PRIO_BUILD + (6 if early_plant else 0)
    place_prio = PRIO_PLACE + (6 if early_plant else 0)
    dig_prio = 17 if len(summary.get("weeds") or []) >= 8 else PRIO_DIG

    for pos in summary.get("unfed_animals") or []:
        add(PRIO_FEED, pos, "FEED")

    plant_by_pos = {(x, y): crop for x, y, crop in summary.get("plants") or []}
    for pos in summary.get("unwatered_plants") or []:
        crop = plant_by_pos.get(pos)
        if crop == "MELON":
            add(PRIO_WATER_MELON, pos, "WATER")
        else:
            add(PRIO_WATER, pos, "WATER")

    for pos in summary.get("uncared_animals") or []:
        add(care_prio, pos, "CARE")
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

    # Fertilize melons/straw in growth windows; wheat secondary
    fert_avail = int(shed.get("FERTILIZER", 0) or 0)
    fert_crops = ("MELON", "STRAWBERRY", "WHEAT")
    for crop_name in fert_crops:
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
        add(dig_prio, pos, "DIG")

    # Cap early pasture builds so opener seeds get planted first
    build_n = pasture_gap
    if early_plant:
        build_n = min(pasture_gap, 2)
    if build_n > 0:
        for pos in pasture_empties(empty)[:build_n]:
            add(build_prio, pos, "BUILD_PASTURE")

    empty_structs = [
        p for p in summary.get("structures_empty") or [] if p not in claimed
    ]
    cow_gap = cow_target - n_cows
    sheep_gap = sheep_target - n_sheep
    shed_cows = int(shed.get("COW", 0) or 0)
    shed_sheep = int(shed.get("SHEEP", 0) or 0)
    for pos in empty_structs:
        tile = _tile_at(farm, pos)
        if not isinstance(tile, dict) or tile.get("kind") != "PASTURE":
            continue
        if cow_gap > 0 or shed_cows > 0:
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
    reserve = 0 if (wave1_rush or seeds_waiting) else pasture_gap
    plant_tiles = plantable_empties(empty, reserve_near_for_pastures=reserve)
    if wave1_rush or seeds_waiting:
        plant_tiles = sort_by_shed_near([p for p in empty if not is_shed_adjacent(p)])

    wheat = crop_counts.get("WHEAT", 0)
    seed_left = {
        "WHEAT": int(seeds.get("WHEAT", 0) or 0),
        "MELON": int(seeds.get("MELON", 0) or 0),
        "STRAWBERRY": int(seeds.get("STRAWBERRY", 0) or 0),
    }

    want_wheat = WHEAT_FEED_TILES
    if day >= SHORT_CYCLE_DAY:
        want_wheat = max(want_wheat, 8)
    # Plant day-0 wheat seeds for feed (avoid buying all feed)
    if day <= 5:
        want_wheat = max(want_wheat, min(12, seed_left["WHEAT"] + wheat))
    if day <= WAVE1_END_DAY and melon < melon_want and day > 0:
        # After day 0, still allow some wheat alongside melons
        want_wheat = max(want_wheat, 4)

    labor = 1 + len(me.get("hands") or [])
    n_unwatered = len(summary.get("unwatered_plants") or [])
    n_unfed = len(summary.get("unfed_animals") or [])
    n_uncared = len(summary.get("uncared_animals") or [])
    if wave1_rush:
        max_new_plants = 99
    else:
        reserved = n_unfed + n_uncared + min(n_unwatered, max(labor - 3, 0))
        floor = 6 if seeds_waiting and day > WAVE1_END_DAY else (3 if (seeds_waiting or straw_waiting) else 0)
        max_new_plants = max(floor, labor - reserved)
    plants_added = 0

    for pos in plant_tiles:
        crop = None
        prio = PRIO_PLANT
        if melon < melon_want and seed_left["MELON"] > 0 and day <= NO_LONG_CROP_AFTER_DAY:
            crop = "MELON"
            melon += 1
            prio = plant_prio
        elif straw < straw_want and seed_left["STRAWBERRY"] > 0 and day <= NO_LONG_CROP_AFTER_DAY:
            crop = "STRAWBERRY"
            straw += 1
            prio = PRIO_PLANT_STRAW
        elif wheat < want_wheat and seed_left["WHEAT"] > 0:
            crop = "WHEAT"
            wheat += 1
        elif day >= SHORT_CYCLE_DAY and seed_left["WHEAT"] > 0:
            crop = "WHEAT"
            wheat += 1
        if crop is None:
            continue
        if plants_added >= max_new_plants:
            break
        seed_left[crop] -= 1
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
        target = nearest_pos(pos, empty_pastures)
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
        if _inv_count(inv, "WHEAT") > 0 and not unfed and (in_cashout or _inv_count(inv, "WHEAT") > 3):
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

        claimed.add(task["pos"])
        if pos == task["pos"]:
            if task["act"] == "PLANT":
                return ["PLANT", task["item"]]
            if task["act"] == "PLACE":
                return ["PLACE", task["item"]]
            return [task["act"]]
        return list(step_toward(pos, task["pos"], board_size))

    if is_shed_adjacent(pos) and not carrying_animal:
        for animal in ("COW", "SHEEP"):
            if empty_pastures and shed.get(animal, 0) > 0:
                return ["PICKUP", animal, 1]
        if (unfed or n_animals) and shed.get("WHEAT", 0) > 0 and _inv_count(inv, "WHEAT") < 3:
            return ["PICKUP", "WHEAT", min(5, int(shed.get("WHEAT", 0)))]

    if empty_pastures and (shed.get("COW", 0) or shed.get("SHEEP", 0)) and not carrying_animal:
        return list(step_toward(pos, nearest_shed_tile(pos), board_size))

    if in_cashout and _inv_total(inv) > 0 and not is_shed_adjacent(pos):
        return list(step_toward(pos, nearest_shed_tile(pos), board_size))

    if not is_shed_adjacent(pos):
        return list(step_toward(pos, nearest_shed_tile(pos), board_size))
    return ["PASS"]
