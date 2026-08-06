"""
Kaggriculture — constant values extracted from README.md

All tables (Object Types, Price Function, Town Shops) and the
Configuration Defaults section, represented as plain Python
data structures.
"""

# ---------------------------------------------------------------------------
# Object Types
# ---------------------------------------------------------------------------
# yield_type            : "ONE_TIME" | "ONGOING" | "NA" (fertilizer)
# seed_cost              : cost to buy one seed/animal/unit
# base_market_price      : base sell price (see MARKET_PARAMS for full curve)
# time_to_first_yield    : days until first harvestable yield
# time_to_max_yield      : days until yield stops increasing (None where NA)
# subsequent_yields      : cadence of repeat production ("none" for one-time)
# max_yield              : cap on total (crops) or held (animals) yield units
# action_cost            : action-point cost (build cost noted separately)
# yield_per_tile_per_day : total units / days tile occupied (crops) or
#                          steady-state production rate (animals)

OBJECT_TYPES = {
    "WHEAT": {
        "yield_type": "ONE_TIME",
        "seed_cost": 10,
        "base_market_price": 25,
        "time_to_first_yield_days": 2,
        "time_to_max_yield_days": 4,
        "subsequent_yields": "none",
        "max_yield": 6,          # 4 unfertilized
        "max_yield_unfertilized": 4,
        "action_cost": 1,
        "yield_per_tile_per_day": 0.80,
    },
    "CARROT": {
        "yield_type": "ONE_TIME",
        "seed_cost": 20,
        "base_market_price": 35,
        "time_to_first_yield_days": 2,
        "time_to_max_yield_days": 3,
        "subsequent_yields": "none",
        "max_yield": 4,          # 3 unfertilized
        "max_yield_unfertilized": 3,
        "action_cost": 1,
        "yield_per_tile_per_day": 0.75,
    },
    "TOMATO": {
        "yield_type": "ONGOING",
        "seed_cost": 50,
        "base_market_price": 60,
        "time_to_first_yield_days": 8,
        "time_to_max_yield_days": 11,
        "subsequent_yields": "every_day_x4",
        "max_yield": 4,
        "action_cost": 1,
        "yield_per_tile_per_day": 0.33,
    },
    "STRAWBERRY": {
        "yield_type": "ONGOING",
        "seed_cost": 100,
        "base_market_price": 120,
        "time_to_first_yield_days": 10,
        "time_to_max_yield_days": 16,
        "subsequent_yields": "every_other_day_x4",
        "max_yield": 4,
        "action_cost": 1,
        "yield_per_tile_per_day": 0.24,
    },
    "MELON": {
        "yield_type": "ONE_TIME",
        "seed_cost": 80,
        "base_market_price": 250,
        "time_to_first_yield_days": 10,
        "time_to_max_yield_days": 10,       # yield caps at age 10
        "bonus_window_end_days": 12,        # watering window ages 6–12
        "subsequent_yields": "none",
        "max_yield": 6,
        "action_cost": 1,
        "yield_per_tile_per_day": 0.55,
    },
    "GOOSE": {  # produces EGG
        "yield_type": "ONGOING",
        "seed_cost": 300,
        "base_market_price": 50,   # price of EGG
        "time_to_first_yield_days": 4,
        "time_to_max_yield_days": None,   # NA
        "subsequent_yields": "every_day_indefinite",
        "max_yield": 4,           # held
        "action_cost": 1,
        "build_cost": 1,          # + build coop
        "yield_per_tile_per_day": 1.00,
    },
    "COW": {  # produces MILK
        "yield_type": "ONGOING",
        "seed_cost": 400,
        "base_market_price": 160,  # price of MILK
        "time_to_first_yield_days": 8,
        "time_to_max_yield_days": None,   # NA
        "subsequent_yields": "every_two_days_indefinite",
        "max_yield": 6,           # held
        "action_cost": 1,
        "build_cost": 1,          # + build pasture
        "yield_per_tile_per_day": 0.50,
    },
    "SHEEP": {  # produces WOOL
        "yield_type": "ONGOING",
        "seed_cost": 500,
        "base_market_price": 200,  # price of WOOL
        "time_to_first_yield_days": 6,
        "time_to_max_yield_days": None,   # NA
        "subsequent_yields": "every_three_days_indefinite",
        "max_yield": 6,           # held
        "action_cost": 1,
        "build_cost": 1,          # + build pasture
        "yield_per_tile_per_day": 0.33,
    },
    "FERTILIZER": {
        "yield_type": "NA",
        "seed_cost": 100,
        "base_market_price": None,   # see MARKET_PARAMS["FERTILIZER"]
        "time_to_first_yield_days": None,
        "time_to_max_yield_days": None,   # X
        "subsequent_yields": None,        # X
        "max_yield": None,
        "action_cost": 1,
        "yield_per_tile_per_day": None,
    },
}

# ---------------------------------------------------------------------------
# The Price Function — per-resource market parameters
# ---------------------------------------------------------------------------
# price(inv) = base + sign * amp * f(|inv - I0|)
#   sign = +1 if inv < I0 (scarcity), -1 if inv > I0 (glut)
#   amp  = target * base / f(T)   (derived, not stored)
#   f in {linear, sq, sqrt, log, log10}   (log uses ln(1+x))
# Floored at $1, rounded to nearest dollar.

MARKET_PARAMS = {
    "WHEAT": {
        "base": 25, "I0": 10_000, "T": 400,
        "below_func": "sqrt", "below_target": 0.80,
        "above_func": "log", "above_target": 0.20,
        # reference prices: P(I0-T)=45, P(I0+T)=20, P(I0+2T)=19
    },
    "CARROT": {
        "base": 35, "I0": 10_000, "T": 450,
        "below_func": "log", "below_target": 0.20,
        "above_func": "sqrt", "above_target": 0.70,
        # P(I0-T)=42, P(I0+T)=10, P(I0+2T)=1
    },
    "TOMATO": {
        "base": 60, "I0": 10_000, "T": 200,
        "below_func": "linear", "below_target": 0.40,
        "above_func": "sqrt", "above_target": 0.60,
        # P(I0-T)=84, P(I0+T)=24, P(I0+2T)=9
    },
    "STRAWBERRY": {
        "base": 120, "I0": 10_000, "T": 100,
        "below_func": "sqrt", "below_target": 0.70,
        "above_func": "linear", "above_target": 1.60,
        # P(I0-T)=204, P(I0+T)=1, P(I0+2T)=1
    },
    "MELON": {
        "base": 250, "I0": 10_000, "T": 300,
        "below_func": "log", "below_target": 0.20,
        "above_func": "sq", "above_target": 3.60,
        # P(I0-T)=300, P(I0+T)=1, P(I0+2T)=1
    },
    "EGG": {
        "base": 50, "I0": 10_000, "T": 332,
        "below_func": "linear", "below_target": 0.40,
        "above_func": "log", "above_target": 0.20,
        # P(I0-T)=70, P(I0+T)=40, P(I0+2T)=39
    },
    "MILK": {
        "base": 160, "I0": 10_000, "T": 122,
        "below_func": "sqrt", "below_target": 0.60,
        "above_func": "linear", "above_target": 1.60,
        # P(I0-T)=256, P(I0+T)=1, P(I0+2T)=1
    },
    "WOOL": {
        "base": 200, "I0": 10_000, "T": 105,
        "below_func": "log", "below_target": 0.20,
        "above_func": "sq", "above_target": 3.20,
        # P(I0-T)=240, P(I0+T)=1, P(I0+2T)=1
    },
    "FERTILIZER": {
        "base": 100, "I0": 10_000, "T": 200,
        "below_func": "linear", "below_target": 0.40,
        "above_func": "linear", "above_target": 0.40,
        # P(I0-T)=140, P(I0+T)=60, P(I0+2T)=20
    },
}

PRICE_FLOOR = 1  # $, minimum sell/buy price

# ---------------------------------------------------------------------------
# Town Shops — demand table
# ---------------------------------------------------------------------------
# Each shop consumes 1 of every listed product every `townShopSellInterval`
# turns (2x for single-product shops, and for entries explicitly marked 2x).

TOWN_SHOPS = {
    "BAKERY": {"demands": ["EGG", "WHEAT"]},
    "PIZZA_SHOP": {"demands": ["MILK", "TOMATO", "WHEAT"]},
    "BRUNCH_SPOT": {"demands": ["EGG", "WHEAT", "STRAWBERRY"]},
    "YARN_STORE": {"demands": ["WOOL"], "multiplier": 2},          # single-product -> 2x
    "ICE_CREAM_SHOP": {"demands": ["STRAWBERRY", "MILK", "WHEAT"]},
    "PET_CAFE": {"demands": ["CARROT"], "multiplier": 2},          # single-product -> 2x
    "SMOOTHIE_SHOP": {"demands": ["STRAWBERRY", "MILK"]},
    "FARMERS_MARKET": {"demands": ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY"]},
}

# Town center consumption schedule (excludes fertilizer)
TOWN_CENTER_BASE_UNITS = 1        # units of each product, days 0-10
TOWN_CENTER_UNITS_AFTER_DAY_10 = 2
TOWN_CENTER_UNITS_AFTER_DAY_20 = 4

# ---------------------------------------------------------------------------
# Farm Hand hiring cost
# ---------------------------------------------------------------------------
# cost = farmHandCostMult * fib(n), n = hires already made today
# fib sequence starts 1, 1, 2, 3, 5, 8, 13, 21, ... (resets each day)

FIBONACCI_HIRE_SEQUENCE = [1, 1, 2, 3, 5, 8, 13, 21]  # extend as needed

# ---------------------------------------------------------------------------
# Land purchase costs
# ---------------------------------------------------------------------------

LAND_COSTS = [1_000, 2_000, 4_000]  # $1k, $2k, $4k for successive quadrants

# ---------------------------------------------------------------------------
# Turn Processing
# ---------------------------------------------------------------------------

TURNS_PER_DAY = 24
DAYS_PER_SEASON = 30
TOTAL_TURNS = TURNS_PER_DAY * DAYS_PER_SEASON  # 720

# ---------------------------------------------------------------------------
# Watering / Feeding thresholds
# ---------------------------------------------------------------------------

NEW_SEED_STARTING_CONSECUTIVE_UNWATERED = 1   # planting day counts as first missed day
NEW_ANIMAL_STARTING_CONSECUTIVE_UNFED = 0     # survives first day unfed
CONSECUTIVE_UNWATERED_TO_WEED = 2
CONSECUTIVE_UNFED_TO_ESCAPE = 2

# ---------------------------------------------------------------------------
# Shed / Board geometry
# ---------------------------------------------------------------------------

DEFAULT_SHED_CAPACITY = 100  # non-seed items; also default of shedCapacity config

# ---------------------------------------------------------------------------
# Configuration Defaults
# ---------------------------------------------------------------------------

CONFIGURATION_DEFAULTS = {
    "episodeSteps": 720,             # 24 turns x 30 days
    "boardSize": 10,                 # 10x10, four 5x5 quadrants
    "startingMoney": 3000,
    "maxMarketOrdersPerTurn": 10,
    "turnsPerDay": 24,
    "shedCapacity": 100,
    "weedSpawnChance": 0.005,        # per-tile probability per end-of-day refresh
    "townShopUnlockInterval": 3,     # days between successive town shop unlocks
    "townShopSellInterval": 4,       # turns between shop consumption ticks
    "townCenterSellInterval": 12,    # turns between town center consumption ticks
    "seed": None,                    # optional deterministic episode seed
}

# ---------------------------------------------------------------------------
# Meta farm targets (2026-08-05 modal ladder farm)
# ---------------------------------------------------------------------------

META_TARGETS = {
    "COW": 8,
    "SHEEP": 5,
    "STRAWBERRY": 6,
    "WHEAT": 1,                 # feed tile; extra wheat bought as product
    "HANDS": 12,
    "LAND": ("NW", "NE", "SW"),  # never SE
}

# Early capital seeds (days 0–4 buy cadence targets, soft)
EARLY_SEED_TARGETS = {
    "WHEAT": 17,
    "MELON": 10,
    "STRAWBERRY": 2,
}

# Metered sell batch sizes (units per SELL order)
SELL_BATCH = {
    "WHEAT": 8,
    "MELON": 8,
    "MILK": 7,
    "WOOL": 7,
    "STRAWBERRY": 8,
    "FERTILIZER": 4,
    "EGG": 8,
    "TOMATO": 4,
    "CARROT": 4,
}

# Soft price floor: sell while price > max(PRICE_FLOOR, floor_frac * base)
SELL_PRICE_FLOOR_FRAC = 0.20

# Day to start unlocking extra land (median first BUY_LAND ~7)
LAND_BUY_DAY = 7

# Shed-adjacent standing tiles (orthogonal access to shed)
SHED_ADJACENT = ((4, 4), (5, 4), (4, 5), (5, 5))
SHED_CENTER = (4.5, 4.5)