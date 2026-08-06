"""
Engine-accurate crop/animal parameters from kaggle_environments kaggriculture.py.

`constants.py` mirrors the README tables; a few fields differ from the live
interpreter (notably MELON.max_yield_day). Decision logic must use these values.
"""

CROPS = {
    "WHEAT": {"seed": 10, "first_yield_day": 2, "max_yield_day": 4, "interval": 0, "max_yield": 6, "ongoing": False},
    "CARROT": {"seed": 20, "first_yield_day": 2, "max_yield_day": 3, "interval": 0, "max_yield": 4, "ongoing": False},
    "TOMATO": {"seed": 50, "first_yield_day": 8, "max_yield_day": 8, "interval": 1, "max_yield": 4, "ongoing": True},
    "STRAWBERRY": {"seed": 100, "first_yield_day": 10, "max_yield_day": 10, "interval": 2, "max_yield": 4, "ongoing": True},
    "MELON": {"seed": 80, "first_yield_day": 10, "max_yield_day": 12, "interval": 0, "max_yield": 6, "ongoing": False},
}

ANIMALS = {
    "GOOSE": {"cost": 300, "structure": "COOP", "first_yield_day": 4, "interval": 1, "max_held": 4, "product": "EGG"},
    "COW": {"cost": 400, "structure": "PASTURE", "first_yield_day": 8, "interval": 2, "max_held": 6, "product": "MILK"},
    "SHEEP": {"cost": 500, "structure": "PASTURE", "first_yield_day": 6, "interval": 3, "max_held": 6, "product": "WOOL"},
}

LAND_ORDER = ["NE", "SW", "SE"]
LAND_PRICES = [1000, 2000, 4000]

SHED_ACCESS = [(4, 4), (5, 4), (4, 5), (5, 5)]  # boardSize=10

# Products that crash hard on glut — sell slowly / only when price is decent.
PREMIUM_PRODUCTS = {"STRAWBERRY", "MELON", "MILK", "WOOL"}

# Staples that absorb oversupply — safe to dump.
STAPLE_PRODUCTS = {"WHEAT", "EGG", "CARROT", "TOMATO", "FERTILIZER"}


def water_bonus_window(crop: str) -> tuple[int, int]:
    """Inclusive (start_age, end_age) for one-time crop watering bonus."""
    cd = CROPS[crop]
    start = (cd["max_yield_day"] + 1) // 2
    return start, cd["max_yield_day"]


def hire_cost(hires_today: int, mult: int = 1) -> int:
    a, b = 1, 1
    for _ in range(hires_today):
        a, b = b, a + b
    return mult * a


def next_land_cost(unlocked_quadrants: list) -> int | None:
    extra = len(unlocked_quadrants) - 1
    if extra >= len(LAND_PRICES):
        return None
    return LAND_PRICES[extra]
