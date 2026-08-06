"""Priority tile jobs and per-unit action assignment."""

from .constants import META_TARGETS
from .pathing import (
    is_shed_adjacent,
    nearest_shed_tile,
    nearest_pos,
    step_toward,
    pasture_empties,
    plantable_empties,
    manhattan,
)


# Task kinds → action emitted when standing on the tile.
# (priority lower = sooner)
PRIO_FEED = 10
PRIO_WATER = 20
PRIO_CARE = 30
PRIO_HARVEST = 40
PRIO_FERT_COLLECT = 50
PRIO_FERTILIZE = 60
PRIO_DIG = 70
PRIO_PLACE = 75   # place waiting animals before building more pastures
PRIO_BUILD = 85
PRIO_PLANT = 100
PRIO_DROP = 110
PRIO_PICKUP = 120


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


def build_tasks(obs, summary, claimed):
    """
    Return a list of task dicts:
      {prio, pos, act, item?}
    `claimed` is a set of positions already assigned this turn.
    """
    player = obs.get("player", 0)
    me = obs["farms"][player]
    private = obs.get("private") or {}
    day = obs.get("day", 0)
    shed = private.get("shed") or {}
    seeds = private.get("seeds") or {}
    farm = me

    crop_counts = summary.get("crop_counts") or {}
    animal_counts = summary.get("animal_counts") or {}
    n_pastures = len(summary.get("pastures") or [])
    n_cows = animal_counts.get("COW", 0)
    n_sheep = animal_counts.get("SHEEP", 0)
    # Build pastures for animals we already own (board+shed+inv) plus a small buffer.
    owned = (
        n_cows + n_sheep
        + int(shed.get("COW", 0) or 0)
        + int(shed.get("SHEEP", 0) or 0)
    )
    target_pastures = min(
        META_TARGETS["COW"] + META_TARGETS["SHEEP"],
        max(owned + 1, 2),
    )
    pasture_gap = max(0, target_pastures - n_pastures)

    empty = [p for p in summary.get("empty") or [] if p not in claimed]
    tasks = []

    def add(prio, pos, act, item=None):
        if pos is None or pos in claimed:
            return
        t = {"prio": prio, "pos": pos, "act": act}
        if item is not None:
            t["item"] = item
        tasks.append(t)

    # Critical animal/crop maintenance.
    for pos in summary.get("unfed_animals") or []:
        add(PRIO_FEED, pos, "FEED")
    for pos in summary.get("unwatered_plants") or []:
        add(PRIO_WATER, pos, "WATER")
    for pos in summary.get("uncared_animals") or []:
        add(PRIO_CARE, pos, "CARE")
    for pos in summary.get("harvestable_animals") or []:
        add(PRIO_HARVEST, pos, "HARVEST")
    for pos in summary.get("harvestable_plants") or []:
        add(PRIO_HARVEST, pos, "HARVEST")
    for pos in summary.get("collectible_fertilizer") or []:
        add(PRIO_FERT_COLLECT, pos, "COLLECT_FERTILIZER")

    # Fertilize wheat only (not melon).
    tiles = farm["tiles"]
    fert_avail = shed.get("FERTILIZER", 0)
    for x, y, crop in summary.get("plants") or []:
        if crop != "WHEAT":
            continue
        tile = tiles[y][x]
        if tile.get("fertilized_until_day", -1) >= day:
            continue
        if fert_avail <= 0:
            break
        add(PRIO_FERTILIZE, (x, y), "FERTILIZE")

    # Dig weeds.
    for pos in summary.get("weeds") or []:
        add(PRIO_DIG, pos, "DIG")

    # Build pastures on nearest empties.
    if pasture_gap > 0:
        for pos in pasture_empties(empty)[:pasture_gap]:
            add(PRIO_BUILD, pos, "BUILD_PASTURE")

    # Place animals onto empty pastures.
    empty_structs = [
        p for p in summary.get("structures_empty") or [] if p not in claimed
    ]
    # Prefer placing cows then sheep based on gaps.
    cow_gap = META_TARGETS["COW"] - n_cows
    sheep_gap = META_TARGETS["SHEEP"] - n_sheep
    for pos in empty_structs:
        tile = _tile_at(farm, pos)
        if tile.get("kind") != "PASTURE":
            continue
        if cow_gap > 0:
            add(PRIO_PLACE, pos, "PLACE", "COW")
            cow_gap -= 1
        elif sheep_gap > 0:
            add(PRIO_PLACE, pos, "PLACE", "SHEEP")
            sheep_gap -= 1

    # Planting: reserve nearest empties for remaining pastures.
    remaining_pasture_slots = pasture_gap
    plant_tiles = plantable_empties(empty, reserve_near_for_pastures=remaining_pasture_slots)

    straw = crop_counts.get("STRAWBERRY", 0)
    wheat = crop_counts.get("WHEAT", 0)
    melon = crop_counts.get("MELON", 0)
    seed_left = {
        "STRAWBERRY": seeds.get("STRAWBERRY", 0),
        "WHEAT": seeds.get("WHEAT", 0),
        "MELON": seeds.get("MELON", 0),
    }

    for pos in plant_tiles:
        crop = None
        if straw < META_TARGETS["STRAWBERRY"] and seed_left["STRAWBERRY"] > 0:
            crop = "STRAWBERRY"
            straw += 1
        elif wheat < META_TARGETS["WHEAT"] and seed_left["WHEAT"] > 0:
            crop = "WHEAT"
            wheat += 1
        elif day < 14 and seed_left["MELON"] > 0 and melon < 12:
            crop = "MELON"
            melon += 1
        elif seed_left["WHEAT"] > 0 and day < 8:
            crop = "WHEAT"
        if crop is None:
            continue
        seed_left[crop] -= 1
        add(PRIO_PLANT, pos, "PLANT", crop)

    return tasks


def _needed_pickup(task, inv, shed):
    """If task needs an item not in inventory, return (item, qty) to pick up."""
    act = task["act"]
    if act == "FEED":
        if _inv_count(inv, "WHEAT") < 1 and shed.get("WHEAT", 0) > 0:
            return "WHEAT", min(5, shed.get("WHEAT", 0))
    if act == "FERTILIZE":
        if _inv_count(inv, "FERTILIZER") < 1 and shed.get("FERTILIZER", 0) > 0:
            return "FERTILIZER", 1
    if act == "PLACE":
        animal = task.get("item")
        if animal and _inv_count(inv, animal) < 1 and shed.get(animal, 0) > 0:
            return animal, 1
    return None


def assign_unit_action(pos, inv, obs, summary, tasks, claimed):
    """
    Choose one farmer/hand op for a unit at `pos` carrying `inv`.
    Mutates `claimed` when a tile task is taken.
    Returns action as a list, e.g. ["WATER"] or ["NORTH"].
    """
    player = obs.get("player", 0)
    me = obs["farms"][player]
    private = obs.get("private") or {}
    shed = private.get("shed") or {}
    board_size = len(me["tiles"])
    unfed = [p for p in (summary.get("unfed_animals") or []) if p not in claimed]
    empty_pastures = [
        p for p in (summary.get("structures_empty") or []) if p not in claimed
    ]
    n_animals = sum((summary.get("animal_counts") or {}).values())

    carrying_cow = _inv_count(inv, "COW")
    carrying_sheep = _inv_count(inv, "SHEEP")
    carrying_animal = "COW" if carrying_cow else ("SHEEP" if carrying_sheep else None)

    # Holding livestock → PLACE on empty pasture. Never DROP animals.
    if carrying_animal and empty_pastures:
        target = nearest_pos(pos, empty_pastures)
        claimed.add(target)
        if pos == target:
            return ["PLACE", carrying_animal]
        return list(step_toward(pos, target, board_size))

    # Feed is existential.
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

    # DROP only produce (DROP clears whole inventory — never while holding livestock).
    if not carrying_animal and is_shed_adjacent(pos):
        produce_keys = (
            "MELON", "STRAWBERRY", "MILK", "WOOL", "FERTILIZER",
            "EGG", "TOMATO", "CARROT",
        )
        if any(_inv_count(inv, k) > 0 for k in produce_keys):
            return ["DROP"]
        if _inv_count(inv, "WHEAT") > 0 and n_animals == 0 and not unfed:
            return ["DROP"]

    if (
        not carrying_animal
        and _inv_total(inv) >= 4
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

        if task["act"] == "PLACE":
            animal = task.get("item")
            if _inv_count(inv, animal) < 1:
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

    # Opportunistic shed pickups — animals first, then feed.
    if is_shed_adjacent(pos) and not carrying_animal:
        for animal in ("COW", "SHEEP"):
            if empty_pastures and shed.get(animal, 0) > 0:
                return ["PICKUP", animal, 1]
        if (unfed or n_animals) and shed.get("WHEAT", 0) > 0 and _inv_count(inv, "WHEAT") < 3:
            return ["PICKUP", "WHEAT", min(5, int(shed.get("WHEAT", 0)))]

    if empty_pastures and (shed.get("COW", 0) or shed.get("SHEEP", 0)) and not carrying_animal:
        return list(step_toward(pos, nearest_shed_tile(pos), board_size))

    if not is_shed_adjacent(pos):
        return list(step_toward(pos, nearest_shed_tile(pos), board_size))
    return ["PASS"]
