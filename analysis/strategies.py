"""Rule-based strategy labels from extracted player features."""

from __future__ import annotations

from typing import Any


def _rev_share(sell_rev: dict, item: str, total: float) -> float:
    if total <= 0:
        return 0.0
    return float(sell_rev.get(item) or 0) / total


def label_strategies(summary: dict[str, Any]) -> list[str]:
    """Return multi-label strategy tags.

    Thresholds are tuned against current leaderboard replay meta (heavy hire,
    sheep/cow open, berry+dairy). Prefer revenue-share and intensity tags that
    actually separate agents in this corpus.
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
        tags.append("animal_open")
    if open_melon >= 8:
        tags.append("melon_rush")
    elif open_melon >= 3:
        tags.append("melon_lite")
    if open_hires >= 7:
        tags.append("hire_open_7")
    elif open_hires >= 5:
        tags.append("hire_open_5")

    # --- board intensity ---
    peak_animals = int(summary.get("peak_animals") or 0)
    if peak_animals >= 16:
        tags.append("animal_max")
    elif peak_animals >= 12:
        tags.append("animal_core")

    geese = int(buy_animal.get("GOOSE") or 0) + int(place.get("GOOSE") or 0)
    if geese > 0 or int(summary.get("build_coop") or 0) > 0:
        tags.append("goose_line")

    median_hires = float(summary.get("median_daily_hires") or 0)
    if median_hires >= 11:
        tags.append("hire_ultra")
    elif median_hires >= 9:
        tags.append("hire_max")

    second_q = summary.get("second_quadrant_day")
    if second_q is not None and second_q <= 8:
        tags.append("land_early")
    elif second_q is not None and second_q <= 15:
        tags.append("land_mid")
    elif int(summary.get("n_quadrants_final") or 1) <= 1:
        tags.append("land_none")

    # --- crops ---
    if int(plant.get("TOMATO") or 0) >= 4:
        tags.append("tomato_line")
    if int(plant.get("STRAWBERRY") or 0) >= 40:
        tags.append("berry_plant_heavy")
    if int(plant.get("MELON") or 0) >= 20:
        tags.append("melon_plant_heavy")

    wheat_ratio = float(summary.get("wheat_self_ratio") or 0)
    if wheat_ratio >= 0.4:
        tags.append("wheat_self_sufficient")
    elif wheat_ratio <= 0.15:
        tags.append("wheat_buyer")

    # --- care / fertilizer ---
    care = int(summary.get("care") or 0)
    feed = int(op_counts.get("FEED") or 0)
    if care >= 350:
        tags.append("animal_care_ultra")
    elif care >= 300 and feed >= 280:
        tags.append("animal_care_heavy")

    fert_sold = int(sell_qty.get("FERTILIZER") or 0)
    fert_used = int(summary.get("fertilize") or 0)
    if fert_sold >= 250:
        tags.append("fert_seller_heavy")
    elif fert_sold >= 150 and fert_sold > fert_used:
        tags.append("fert_seller")

    # --- revenue engines (most discriminative) ---
    total_rev = float(summary.get("total_sell_revenue") or 0) or 1.0
    shares = {
        "berry": _rev_share(sell_rev, "STRAWBERRY", total_rev),
        "dairy": _rev_share(sell_rev, "MILK", total_rev),
        "wool": _rev_share(sell_rev, "WOOL", total_rev),
        "melon": _rev_share(sell_rev, "MELON", total_rev),
        "egg": _rev_share(sell_rev, "EGG", total_rev),
        "wheat": _rev_share(sell_rev, "WHEAT", total_rev),
    }
    primary = max(shares, key=shares.get)
    if shares[primary] >= 0.18:
        tags.append(f"primary_{primary}")

    if shares["berry"] >= 0.28:
        tags.append("berry_engine")
    elif shares["berry"] >= 0.18:
        tags.append("berry_support")

    if shares["dairy"] >= 0.28:
        tags.append("dairy_focus")
    elif shares["dairy"] >= 0.18:
        tags.append("dairy_support")

    if shares["wool"] >= 0.25:
        tags.append("wool_focus")
    elif shares["wool"] >= 0.15:
        tags.append("wool_support")

    if shares["melon"] >= 0.25:
        tags.append("melon_focus")
    elif shares["melon"] >= 0.15:
        tags.append("melon_support")

    if not tags:
        tags.append("unclassified")
    return tags
