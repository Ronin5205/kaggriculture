"""
Kaggriculture — tile state analysis & update functions.

Operates on the `tile` structures described in the README's Observation
Format section:

    None                         -> empty unlocked tile
    "LOCKED"                     -> tile in an unbought quadrant
    {"kind": "PLANT", ...}       -> a growing plant
    {"kind": "WEED"}             -> a weed
    {"kind": "COOP"/"PASTURE",   -> an animal structure, occupied or not
     "animal": ... }

A player's full board state is `farm["tiles"]`, a `tiles[y][x]` grid (see
Observation Format). Functions here operate both on a single tile dict and
on the whole `farm` dict.

TWO REFRESH CADENCES:
Most plant/animal state (watering/feeding streaks, weed/escape conversion,
crop growth, scheduled animal production) changes on the "Day refresh" step
of Turn Processing Order, i.e. once per in-game day -> `refresh_*_end_of_day`.

Post-lifespan decay is the exception: the README states it happens "every
other turn", and the plant schema field is named `max_lifespan_step` (a
*step*, i.e. an absolute turn count = day * turnsPerDay + hour), not
`max_lifespan_day`. So decay is tracked and applied at turn granularity via
`refresh_*_end_of_turn`, which should be called every turn regardless of
day boundaries, alongside the once-per-day functions.
"""

import random

from .constants import (
    OBJECT_TYPES,
    CONSECUTIVE_UNWATERED_TO_WEED,
    CONSECUTIVE_UNFED_TO_ESCAPE,
    TURNS_PER_DAY,
)

# ---------------------------------------------------------------------------
# Crop / animal groupings
# ---------------------------------------------------------------------------

ONE_TIME_CROPS = {"WHEAT", "CARROT", "MELON"}
ONGOING_CROPS = {"TOMATO", "STRAWBERRY"}
ANIMALS = {"GOOSE", "COW", "SHEEP"}

# Cadence (in days) of scheduled/ongoing production.
PRODUCTION_INTERVAL_DAYS = {
    "TOMATO": 1,      # every day
    "STRAWBERRY": 2,  # every other day
    "GOOSE": 1,       # every day
    "COW": 2,         # every two days
    "SHEEP": 3,       # every three days
}

ANIMAL_TO_PRODUCT = {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}
ANIMAL_TO_STRUCTURE = {"GOOSE": "COOP", "COW": "PASTURE", "SHEEP": "PASTURE"}


def day_to_step(day, hour=0):
    """Absolute turn/step index for a given (day, hour), per turnsPerDay."""
    return day * TURNS_PER_DAY + hour


# ===========================================================================
# Tile classification / analysis
# ===========================================================================

def tile_type(tile):
    """Return a short type tag for any tile value."""
    if tile is None:
        return "EMPTY"
    if tile == "LOCKED":
        return "LOCKED"
    if isinstance(tile, dict):
        return tile.get("kind", "UNKNOWN")
    return "UNKNOWN"


def is_empty(tile):
    return tile is None


def is_locked(tile):
    return tile == "LOCKED"


def is_weed(tile):
    return isinstance(tile, dict) and tile.get("kind") == "WEED"


def is_plant(tile):
    return isinstance(tile, dict) and tile.get("kind") == "PLANT"


def is_animal_structure(tile):
    return isinstance(tile, dict) and tile.get("kind") in ("COOP", "PASTURE")


def is_occupied_animal_structure(tile):
    return is_animal_structure(tile) and tile.get("animal") is not None


def is_buildable(tile):
    """A tile can host BUILD_COOP / BUILD_PASTURE only if unlocked+empty."""
    return is_empty(tile)


def plant_age(tile, current_day):
    """Age in days of a plant tile as of `current_day`."""
    if not is_plant(tile):
        raise ValueError("plant_age() requires a PLANT tile")
    return current_day - tile["planted_day"]


def animal_age(tile, current_day):
    """Age in days of the animal occupying a structure tile."""
    if not is_occupied_animal_structure(tile):
        raise ValueError("animal_age() requires an occupied structure tile")
    return current_day - tile["placed_day"]


def describe_tile(tile, current_day=None):
    """Human-readable one-line summary of a tile, for debugging/logging."""
    kind = tile_type(tile)
    if kind == "EMPTY":
        return "empty"
    if kind == "LOCKED":
        return "locked"
    if kind == "WEED":
        return "weed"
    if kind == "PLANT":
        age = f", age {plant_age(tile, current_day)}" if current_day is not None else ""
        return (f"{tile['crop']} (yield={tile['yield_units']}, "
                f"unwatered={tile['consecutive_unwatered']}{age})")
    if kind in ("COOP", "PASTURE"):
        if tile["animal"] is None:
            return f"empty {kind.lower()}"
        age = f", age {animal_age(tile, current_day)}" if current_day is not None else ""
        return (f"{tile['animal']} on {kind.lower()} "
                f"(held={tile['yield_units']}, unfed={tile['consecutive_unfed']}{age})")
    return "unknown"


def plant_needs_water(tile, day):
    """Seb-style watering: skip safe days; water survival + growth windows only.

    After a watered day, consecutive_unwatered is 0 and the plant can skip one
    day (weed threshold is 2). Day-1 Seb literally issued 0 WATER ops.
    Always water when consecutive_unwatered >= 1 (includes planting day), or
    when a yield-growth window is active.
    """
    if not is_plant(tile) or tile.get("watered_today"):
        return False
    if int(tile.get("consecutive_unwatered") or 0) >= 1:
        return True
    if day is None:
        return False
    crop = tile.get("crop")
    planted = tile.get("planted_day")
    if planted is None:
        return False
    age = int(day) - int(planted)
    if crop in ONE_TIME_CROPS:
        bonus_start, bonus_end = _one_time_bonus_window(crop)
        if bonus_start <= age <= bonus_end:
            return True
    elif crop in ONGOING_CROPS:
        schedule = _ongoing_schedule(crop)
        if age in schedule:
            return True
    return False


def analyze_farm(farm, current_day=None):
    """
    Scan a player's `farm["tiles"]` grid and summarize its state.

    Returns a dict with counts and coordinate lists, useful for agent
    decision-making (e.g. "which tiles need watering right now").
    """
    summary = {
        "empty": [],
        "locked": [],
        "weeds": [],
        "plants": [],            # (x, y, crop)
        "unwatered_plants": [],  # not watered_today (raw flag)
        "needs_water_plants": [],  # Seb-style: survival or growth window
        "harvestable_plants": [],  # plants with yield_units > 0
        "structures_empty": [],  # unoccupied coop/pasture
        "structures_occupied": [],  # (x, y, animal)
        "unfed_animals": [],
        "uncared_animals": [],   # occupied, not cared today
        "harvestable_animals": [],  # occupied with yield_units > 0
        "collectible_fertilizer": [],
        "pastures": [],          # all PASTURE tiles (x, y)
        "crop_counts": {},       # crop -> count
        "animal_counts": {},     # animal -> count
    }

    tiles = farm["tiles"]
    for y, row in enumerate(tiles):
        for x, tile in enumerate(row):
            if is_empty(tile):
                summary["empty"].append((x, y))
            elif is_locked(tile):
                summary["locked"].append((x, y))
            elif is_weed(tile):
                summary["weeds"].append((x, y))
            elif is_plant(tile):
                crop = tile["crop"]
                summary["plants"].append((x, y, crop))
                summary["crop_counts"][crop] = summary["crop_counts"].get(crop, 0) + 1
                if not tile["watered_today"]:
                    summary["unwatered_plants"].append((x, y))
                if plant_needs_water(tile, current_day):
                    summary["needs_water_plants"].append((x, y))
                if tile["yield_units"] > 0:
                    summary["harvestable_plants"].append((x, y))
            elif is_animal_structure(tile):
                if tile.get("kind") == "PASTURE":
                    summary["pastures"].append((x, y))
                if tile.get("animal") is None:
                    summary["structures_empty"].append((x, y))
                else:
                    animal = tile["animal"]
                    summary["structures_occupied"].append((x, y, animal))
                    summary["animal_counts"][animal] = (
                        summary["animal_counts"].get(animal, 0) + 1
                    )
                    if not tile.get("fed_today"):
                        summary["unfed_animals"].append((x, y))
                    if not tile.get("cared_today"):
                        summary["uncared_animals"].append((x, y))
                    if tile.get("yield_units", 0) > 0:
                        summary["harvestable_animals"].append((x, y))
                    if tile.get("fertilizer_available"):
                        summary["collectible_fertilizer"].append((x, y))

    return summary


# ===========================================================================
# Tile creation
# ===========================================================================

def new_plant(crop, planted_day):
    """Build a fresh PLANT tile dict for `crop`, planted on `planted_day`."""
    if crop not in OBJECT_TYPES:
        raise ValueError(f"Unknown crop: {crop}")
    return {
        "kind": "PLANT",
        "crop": crop,
        "planted_day": planted_day,
        "watered_today": False,
        "consecutive_unwatered": 1,  # planting day counts as the first missed day
        "yield_units": 0,
        "max_lifespan_step": -1,
        "fertilized_until_day": -1,
    }


def new_animal_structure(kind):
    """Build a fresh, unoccupied COOP or PASTURE tile dict."""
    if kind not in ("COOP", "PASTURE"):
        raise ValueError("kind must be 'COOP' or 'PASTURE'")
    return {
        "kind": kind,
        "animal": None,
        "placed_day": None,
        "yield_units": 0,
        "fed_today": False,
        "consecutive_unfed": 0,
        "cared_today": False,
        "fertilizer_available": False,
        "pending_care_bonus": 0,
    }


# ===========================================================================
# Player action handlers (single tile, mutate + return success)
# ===========================================================================

def plant_seed(tile, crop, day):
    """
    PLANT action. Only legal on an empty, unlocked tile.
    Returns (success: bool, new_tile).
    """
    if not is_empty(tile):
        return False, tile
    return True, new_plant(crop, day)


def water_tile(tile):
    """
    WATER action. No-op if not a plant or already watered today.
    Returns success bool; mutates tile in place.
    """
    if not is_plant(tile):
        return False
    if tile["watered_today"]:
        return False  # no-op, already watered
    tile["watered_today"] = True
    return True


def fertilize_tile(tile, day):
    """
    FERTILIZE action. Doubles the per-day yield bonus for the next 3 days
    (only on days the plant is also watered).
    """
    if not is_plant(tile):
        return False
    tile["fertilized_until_day"] = day + 3
    return True


def harvest_tile(tile, day):
    """
    HARVEST action. Dispatches by tile kind, since the same action name
    covers both "gather produce from a plant" and "collect eggs/milk/wool
    from an animal".

    Returns (units_harvested, new_tile).
    """
    if is_plant(tile):
        return _harvest_plant(tile)
    if is_occupied_animal_structure(tile):
        return _harvest_animal_product(tile)
    return 0, tile


def _harvest_plant(tile):
    """
    HARVEST for a PLANT tile.
      - No yield yet: nothing to harvest -> (0, tile).
      - One-time crops: harvest empties the plant AND removes it from the
        map (tile becomes None), matching "no subsequent yields".
      - Ongoing crops: harvest empties yield_units but the plant stays;
        yield_units re-accumulates at the next scheduled production.
    """
    units = tile["yield_units"]
    if units <= 0:
        return 0, tile

    crop = tile["crop"]
    if crop in ONE_TIME_CROPS:
        return units, None  # plant removed from the map
    else:
        tile["yield_units"] = 0
        return units, tile


def _harvest_animal_product(tile):
    """
    HARVEST for an occupied COOP/PASTURE: "Collect the eggs/milk/wool
    produced by the animal." Empties `yield_units`; the animal and
    structure stay in place.
    """
    units = tile["yield_units"]
    if units <= 0:
        return 0, tile
    tile["yield_units"] = 0
    return units, tile


def build_structure(tile, kind):
    """BUILD_COOP / BUILD_PASTURE. Only legal on an empty tile."""
    if not is_buildable(tile):
        return False, tile
    return True, new_animal_structure(kind)


def place_animal(tile, animal, day):
    """
    PLACE action for an animal onto a matching, unoccupied structure
    (GOOSE -> COOP, COW/SHEEP -> PASTURE).
    """
    if not is_animal_structure(tile) or tile["animal"] is not None:
        return False
    expected_structure = ANIMAL_TO_STRUCTURE.get(animal)
    if tile["kind"] != expected_structure:
        return False
    tile["animal"] = animal
    tile["placed_day"] = day
    tile["yield_units"] = 0
    tile["fed_today"] = False
    tile["consecutive_unfed"] = 0  # survives its first day unfed
    tile["cared_today"] = False
    tile["fertilizer_available"] = False
    tile["pending_care_bonus"] = 0
    return True


def feed_tile(tile):
    """FEED action. No-op if not an occupied structure or already fed today."""
    if not is_occupied_animal_structure(tile):
        return False
    if tile["fed_today"]:
        return False
    tile["fed_today"] = True
    return True


def care_tile(tile):
    """CARE action. No-op if not an occupied structure or already cared today."""
    if not is_occupied_animal_structure(tile):
        return False
    if tile["cared_today"]:
        return False
    tile["cared_today"] = True
    return True


def collect_fertilizer(tile):
    """
    COLLECT_FERTILIZER action. Returns units collected (0 or 1).
    Uncollected fertilizer does not accumulate across days.
    """
    if not is_occupied_animal_structure(tile):
        return 0
    if not tile["fertilizer_available"]:
        return 0
    tile["fertilizer_available"] = False
    return 1


def dig_tile(tile):
    """
    DIG action. Removes a plant or weed, or an *empty* coop/pasture.
    No-op (returns False) on an occupied structure.
    Returns (success: bool, new_tile).
    """
    if is_plant(tile) or is_weed(tile):
        return True, None
    if is_animal_structure(tile) and tile["animal"] is None:
        return True, None
    return False, tile


# ===========================================================================
# End-of-day refresh
# ===========================================================================

def _one_time_bonus_window(crop):
    """(start_age, end_age) inclusive window where watering grows yield.

    Window starts at ceil(bonus_end / 2) ≈ (bonus_end + 1) // 2.
    Melon uses bonus_window_end_days=12 (ages 6–12) while yield caps at
    time_to_max_yield_days=10.
    """
    cfg = OBJECT_TYPES[crop]
    bonus_end = cfg.get("bonus_window_end_days") or cfg["time_to_max_yield_days"]
    bonus_start = (bonus_end + 1) // 2
    return bonus_start, bonus_end


def _ongoing_schedule(crop):
    """List of ages (days since planting) at which scheduled yield fires."""
    cfg = OBJECT_TYPES[crop]
    first_yield = cfg["time_to_first_yield_days"]
    interval = PRODUCTION_INTERVAL_DAYS[crop]
    return [first_yield + i * interval for i in range(cfg["max_yield"])]


def _refresh_plant_end_of_day(tile, day):
    """Apply one day's worth of watering/growth/decay rules to a PLANT tile."""
    crop = tile["crop"]
    cfg = OBJECT_TYPES[crop]
    age = day - tile["planted_day"]
    watered = tile["watered_today"]
    fertilized = tile["fertilized_until_day"] >= day

    # 1. Watering streak -> possible weed conversion.
    tile["consecutive_unwatered"] = 0 if watered else tile["consecutive_unwatered"] + 1
    if tile["consecutive_unwatered"] >= CONSECUTIVE_UNWATERED_TO_WEED:
        return {"kind": "WEED"}

    if crop in ONE_TIME_CROPS:
        bonus_start, bonus_end = _one_time_bonus_window(crop)
        first_yield = cfg["time_to_first_yield_days"]
        max_yield_day = cfg["time_to_max_yield_days"]

        if watered and bonus_start <= age <= bonus_end:
            if tile["yield_units"] == 0:
                tile["yield_units"] = 1
            growth = 2 if fertilized else 1
            tile["yield_units"] = min(cfg["max_yield"], tile["yield_units"] + growth)
        elif age >= first_yield and tile["yield_units"] == 0:
            tile["yield_units"] = 1

        # Lifespan decay begins one day after time_to_max_yield_days.
        if tile["max_lifespan_step"] == -1 and age >= max_yield_day + 1:
            tile["max_lifespan_step"] = day_to_step(day + 1)

    elif crop in ONGOING_CROPS:
        schedule = _ongoing_schedule(crop)
        if watered and age in schedule:
            growth = 2 if fertilized else 1
            tile["yield_units"] += growth

        # Decay begins one day after cumulative production count hits max_yield.
        fired_count = sum(1 for s in schedule if s <= age)
        if fired_count >= cfg["max_yield"] and tile["max_lifespan_step"] == -1:
            tile["max_lifespan_step"] = day_to_step(day + 1)

    tile["watered_today"] = False
    return tile


def _refresh_animal_end_of_day(tile, day):
    """Apply one day's worth of feeding/care/production rules to a structure tile."""
    if tile["animal"] is None:
        return tile  # unoccupied structure: nothing to refresh

    fed = tile["fed_today"]
    cared = tile["cared_today"]

    tile["consecutive_unfed"] = 0 if fed else tile["consecutive_unfed"] + 1
    if tile["consecutive_unfed"] >= CONSECUTIVE_UNFED_TO_ESCAPE:
        # Animal escapes; structure remains, now empty.
        return new_animal_structure(tile["kind"])

    animal = tile["animal"]
    cfg = OBJECT_TYPES[animal]
    interval = PRODUCTION_INTERVAL_DAYS[animal]
    age = day - tile["placed_day"]

    # Care bonus banking — basic needs (feeding) first.
    if fed and cared:
        tile["pending_care_bonus"] += 1

    # Scheduled production.
    if age >= cfg["time_to_first_yield_days"] and \
            (age - cfg["time_to_first_yield_days"]) % interval == 0:
        if fed:
            bonus = tile["pending_care_bonus"]
        else:
            bonus = 0  # unfed on production day: base unit still produced, bank lost
        tile["pending_care_bonus"] = 0
        tile["yield_units"] = min(cfg["max_yield"], tile["yield_units"] + 1 + bonus)

    # Every surviving animal makes 1 fertilizer available at end of day.
    tile["fertilizer_available"] = True

    tile["fed_today"] = False
    tile["cared_today"] = False
    return tile


def refresh_tile_end_of_day(tile, day):
    """Dispatch end-of-day refresh for a single tile based on its kind."""
    if is_plant(tile):
        return _refresh_plant_end_of_day(tile, day)
    if is_animal_structure(tile):
        return _refresh_animal_end_of_day(tile, day)
    return tile  # None, "LOCKED", WEED all pass through unchanged


def refresh_farm_end_of_day(farm, day, weed_spawn_chance=0.005, rng=None):
    """
    Run the full end-of-day refresh over every tile in a player's farm:
      - plants/animals age, grow, or die (weed/escape) per the rules above
      - empty unlocked tiles may spawn a weed (`weed_spawn_chance` each)

    Does NOT apply post-lifespan decay — that's turn-granular, see
    refresh_farm_end_of_turn(). Mutates and returns `farm["tiles"]` in place.
    """
    rng = rng or random
    tiles = farm["tiles"]
    for y, row in enumerate(tiles):
        for x, tile in enumerate(row):
            if is_empty(tile):
                if rng.random() < weed_spawn_chance:
                    tiles[y][x] = {"kind": "WEED"}
                continue
            tiles[y][x] = refresh_tile_end_of_day(tile, day)
    return tiles


# ===========================================================================
# End-of-turn refresh (post-lifespan decay only)
# ===========================================================================
#
# "Once a plant has hit its maximum lifespan, the total yield available on
# the plant will reduce by 1 every other turn until it hits 0, at which
# point the plant becomes a weed." This is the one piece of plant state
# that ticks on turns, not days, so it's handled separately from the day
# refresh above and should be called every turn (e.g. from step 4, "Farm
# update", of Turn Processing Order).

def refresh_tile_end_of_turn(tile, step):
    """
    Apply one turn's worth of post-lifespan decay to a single tile.
    No-op for anything that isn't a decaying plant. Returns the (possibly
    replaced) tile.
    """
    if not is_plant(tile):
        return tile

    start_step = tile["max_lifespan_step"]
    if start_step == -1 or step < start_step:
        return tile  # decay hasn't started yet

    # Decays by 1 unit every OTHER turn starting at start_step.
    if (step - start_step) % 2 == 0:
        tile["yield_units"] = max(0, tile["yield_units"] - 1)
        if tile["yield_units"] == 0:
            return {"kind": "WEED"}
    return tile


def refresh_farm_end_of_turn(farm, step):
    """
    Run post-lifespan decay over every tile in a player's farm for the
    current absolute turn `step` (see day_to_step()). Call this every
    turn; it's a no-op for tiles that aren't past their lifespan.

    Mutates and returns `farm["tiles"]` in place.
    """
    tiles = farm["tiles"]
    for y, row in enumerate(tiles):
        for x, tile in enumerate(row):
            if is_plant(tile):
                tiles[y][x] = refresh_tile_end_of_turn(tile, step)
    return tiles


# ===========================================================================
# Batch PLANT-order resolution
# ===========================================================================
#
# "If you try to plant too many in a specific turn, none are planted
# — ie if you have 1 melon seed, but two units do the PLANT MELON command."
# This requires looking at all PLANT commands issued by a player's
# farmer/hands in a single turn together, since a single tile-level
# plant_seed() call can't see the other requests or the seed inventory.

def resolve_plant_orders(farm, requests, day, seed_counts):
    """
    Resolve a batch of PLANT commands issued in the same turn.

    requests:     list of (x, y, crop) tuples — one per farmer/hand
                   command this turn.
    seed_counts:  {crop: available_seed_count} for this player, taken
                   from the private observation's "seeds" dict.

    Returns (results, updated_seed_counts):
      results is a list of (x, y, crop, success: bool) aligned with
      `requests`. `farm["tiles"]` is mutated in place for successes.
      A crop group only succeeds as a whole if seed_counts[crop] is
      enough to cover every request for that crop this turn; a crop
      group also fails entirely if any target tile in it isn't a plain
      empty tile (matches "if you try to plant too many ... none are
      planted", generalized to any within-turn conflict for that crop).
    """
    tiles = farm["tiles"]
    seed_counts = dict(seed_counts)  # don't mutate caller's dict

    by_crop = {}
    for x, y, crop in requests:
        by_crop.setdefault(crop, []).append((x, y))

    results = {}
    for crop, coords in by_crop.items():
        available = seed_counts.get(crop, 0)
        all_targets_plantable = all(is_empty(tiles[y][x]) for x, y in coords)
        crop_group_ok = (len(coords) <= available) and all_targets_plantable

        if crop_group_ok:
            for x, y in coords:
                tiles[y][x] = new_plant(crop, day)
                results[(x, y, crop)] = True
            seed_counts[crop] = available - len(coords)
        else:
            for x, y in coords:
                results[(x, y, crop)] = False

    ordered_results = [(x, y, crop, results[(x, y, crop)]) for x, y, crop in requests]
    return ordered_results, seed_counts