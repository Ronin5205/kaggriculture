"""Feature-based multi-labels from extracted player stats."""

from __future__ import annotations

from typing import Any

from .schema import ANIMALS, CROPS, PRODUCTS

# Plant intensity: (high, mid) plant counts per crop.
PLANT_THRESH: dict[str, tuple[int, int]] = {
    "WHEAT": (40, 15),
    "CARROT": (20, 5),
    "TOMATO": (15, 4),
    "STRAWBERRY": (40, 15),
    "MELON": (20, 8),
}

REV_HIGH = 0.25
REV_MID = 0.15
PRIMARY_MIN = 0.15


def _rev_share(sell_rev: dict, item: str, total: float) -> float:
    if total <= 0:
        return 0.0
    return float(sell_rev.get(item) or 0) / total


def _append_intensity(tags: list[str], prefix: str, value: float, high: float, mid: float) -> None:
    if value >= high:
        tags.append(f"{prefix}_high")
    elif value >= mid:
        tags.append(f"{prefix}_mid")


def label_strategies(summary: dict[str, Any]) -> list[str]:
    """Return multi-label behavioral feature tags.

    Tags describe measured intensities (open buys, board scale, plant mix,
    care/fert use, revenue shares across every product). Thresholds are
    heuristics — retune when the corpus distribution shifts.
    """
    tags: list[str] = []

    open_animals = int(summary.get("open_animals") or 0)
    open_melon = int(summary.get("open_melon_seeds") or 0)
    open_hires = int(summary.get("open_hires") or 0)
    buy_animal = summary.get("buy_animal") or {}
    plant = summary.get("plant_counts") or {}
    sell_rev = summary.get("sell_revenue") or {}
    sell_qty = summary.get("sell_qty") or {}
    place = summary.get("place_animal") or {}
    op_counts = summary.get("op_counts") or {}

    # --- opening ---
    if open_animals >= 2:
        tags.append("open_animals")
    _append_intensity(tags, "open_melon", open_melon, 8, 3)
    _append_intensity(tags, "open_hire", open_hires, 7, 5)

    # --- board intensity ---
    peak_animals = int(summary.get("peak_animals") or 0)
    _append_intensity(tags, "animals", peak_animals, 16, 12)

    for animal in ANIMALS:
        n = int(buy_animal.get(animal) or 0) + int(place.get(animal) or 0)
        if n > 0 or (animal == "GOOSE" and int(summary.get("build_coop") or 0) > 0):
            tags.append(animal.lower())

    median_hires = float(summary.get("median_daily_hires") or 0)
    _append_intensity(tags, "hires", median_hires, 11, 9)

    second_q = summary.get("second_quadrant_day")
    if second_q is not None and second_q <= 8:
        tags.append("land_early")
    elif second_q is not None and second_q <= 15:
        tags.append("land_mid")
    elif int(summary.get("n_quadrants_final") or 1) <= 1:
        tags.append("land_none")

    # --- crops (all five) ---
    for crop in CROPS:
        high, mid = PLANT_THRESH[crop]
        _append_intensity(tags, f"plants_{crop.lower()}", int(plant.get(crop) or 0), high, mid)

    wheat_ratio = float(summary.get("wheat_self_ratio") or 0)
    if wheat_ratio >= 0.4:
        tags.append("wheat_self_high")
    elif wheat_ratio <= 0.15:
        tags.append("wheat_self_low")

    # --- care / fertilizer qty ---
    care = int(summary.get("care") or 0)
    feed = int(op_counts.get("FEED") or 0)
    if care >= 350:
        tags.append("care_high")
    elif care >= 300 and feed >= 280:
        tags.append("care_mid")

    fert_sold = int(sell_qty.get("FERTILIZER") or 0)
    fert_used = int(summary.get("fertilize") or 0)
    if fert_sold >= 250:
        tags.append("fert_sell_high")
    elif fert_sold >= 150 and fert_sold > fert_used:
        tags.append("fert_sell_mid")

    # --- revenue mix (every sellable product) ---
    total_rev = float(summary.get("total_sell_revenue") or 0) or 1.0
    shares = {prod.lower(): _rev_share(sell_rev, prod, total_rev) for prod in PRODUCTS}
    primary = max(shares, key=shares.get)
    if shares[primary] >= PRIMARY_MIN:
        tags.append(f"primary_{primary}")

    for key, share in shares.items():
        _append_intensity(tags, f"rev_{key}", share, REV_HIGH, REV_MID)

    if not tags:
        tags.append("unclassified")
    return tags
