"""Matplotlib visualizations for replay analysis outputs."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


PRODUCT_COLORS = {
    "WHEAT": "#c4a35a",
    "MELON": "#2e8b57",
    "STRAWBERRY": "#d62828",
    "MILK": "#4ea8de",
    "WOOL": "#9b5de5",
    "EGG": "#f4a261",
    "FERTILIZER": "#6a994e",
    "CARROT": "#e76f51",
    "TOMATO": "#e63946",
}


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return path


def _pick_showcase_episode(corpus: dict[str, Any], episode_id: str | None = None) -> str | None:
    if episode_id:
        return str(episode_id)
    eps = corpus.get("episodes") or []
    if not eps:
        return None
    best = max(eps, key=lambda e: max(float(e["reward0"]), float(e["reward1"])))
    return str(best["episode_id"])


def plot_money_curves(corpus: dict[str, Any], out: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 5.5))
    by_day: dict[int, list[float]] = defaultdict(list)
    series: dict[tuple[str, int], list[tuple[int, float]]] = defaultdict(list)

    for row in corpus.get("daily") or []:
        if int(row.get("hour") or 0) != 0:
            continue
        day = int(row["day"])
        money = float(row["money"])
        by_day[day].append(money)
        key = (str(row["episode_id"]), int(row["player"]))
        series[key].append((day, money))

    for pts in series.values():
        pts = sorted(pts)
        ax.plot(
            [p[0] for p in pts],
            [p[1] for p in pts],
            color="#8b9bab",
            alpha=0.18,
            linewidth=1,
        )

    days = sorted(by_day)
    if days:
        means = [float(np.mean(by_day[d])) for d in days]
        p25 = [float(np.percentile(by_day[d], 25)) for d in days]
        p75 = [float(np.percentile(by_day[d], 75)) for d in days]
        ax.fill_between(days, p25, p75, color="#1d4e89", alpha=0.2, label="IQR")
        ax.plot(days, means, color="#1d4e89", linewidth=2.4, label="Corpus mean")

    ax.set_title("Bank balance over the season")
    ax.set_xlabel("Day")
    ax.set_ylabel("Money")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.25)
    return _save(fig, out / "money_curves.png")


def plot_agents(corpus: dict[str, Any], out: Path, top_n: int = 12) -> Path:
    agents = list(corpus.get("agents") or [])[:top_n]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    if not agents:
        ax.text(0.5, 0.5, "No agent data", ha="center")
        return _save(fig, out / "agents_avg_money.png")

    names = [a["agent"][:22] for a in agents][::-1]
    vals = [a["avg_money"] for a in agents][::-1]
    colors = ["#2a9d8f" if a["win_rate"] >= 0.5 else "#e76f51" for a in agents][::-1]
    ax.barh(names, vals, color=colors)
    ax.set_xlabel("Average final money")
    ax.set_title(f"Top {len(agents)} agents by average score")
    ax.grid(True, axis="x", alpha=0.25)
    return _save(fig, out / "agents_avg_money.png")


def plot_strategies(corpus: dict[str, Any], out: Path, top_n: int = 12) -> Path:
    rows = [r for r in (corpus.get("strategies") or []) if r["games"] >= 3][:top_n]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    if not rows:
        rows = list(corpus.get("strategies") or [])[:top_n]
    names = [r["strategy"] for r in rows][::-1]
    vals = [r["avg_money"] for r in rows][::-1]
    ax.barh(names, vals, color="#457b9d")
    ax.set_xlabel("Average final money")
    ax.set_title("Strategy tags by average score")
    ax.grid(True, axis="x", alpha=0.25)
    return _save(fig, out / "strategies_avg_money.png")


def plot_revenue_mix(corpus: dict[str, Any], out: Path) -> Path:
    keys = [
        ("rev_wheat", "WHEAT"),
        ("rev_melon", "MELON"),
        ("rev_strawberry", "STRAWBERRY"),
        ("rev_milk", "MILK"),
        ("rev_wool", "WOOL"),
        ("rev_egg", "EGG"),
        ("rev_fertilizer", "FERTILIZER"),
    ]
    totals = Counter()
    for row in corpus.get("players") or []:
        for col, name in keys:
            totals[name] += float(row.get(col) or 0)

    fig, ax = plt.subplots(figsize=(8, 8))
    labels = [k for k, v in totals.most_common() if v > 0]
    sizes = [totals[k] for k in labels]
    colors = [PRODUCT_COLORS.get(k, "#888888") for k in labels]
    if not sizes:
        ax.text(0.5, 0.5, "No revenue data", ha="center")
    else:
        ax.pie(sizes, labels=labels, colors=colors, autopct="%1.1f%%", startangle=90)
        ax.set_title("Corpus sell-revenue mix")
    return _save(fig, out / "revenue_mix.png")


def plot_action_mix(corpus: dict[str, Any], out: Path) -> Path:
    ops = list(corpus.get("op_counts") or [])
    fig, ax = plt.subplots(figsize=(10, 5.5))
    if not ops:
        ax.text(0.5, 0.5, "No action data", ha="center")
        return _save(fig, out / "action_mix.png")

    # Collapse moves.
    collapsed: Counter = Counter()
    for row in ops:
        op = row["op"]
        n = int(row["count"])
        if op in {"NORTH", "SOUTH", "EAST", "WEST"}:
            collapsed["MOVE"] += n
        else:
            collapsed[op] += n
    top = collapsed.most_common(12)
    labels = [k for k, _ in top][::-1]
    vals = [v for _, v in top][::-1]
    ax.barh(labels, vals, color="#264653")
    ax.set_xlabel("Count (all unit-actions across corpus)")
    ax.set_title("Unit action mix")
    ax.grid(True, axis="x", alpha=0.25)
    return _save(fig, out / "action_mix.png")


def plot_ops_by_day(corpus: dict[str, Any], out: Path) -> Path:
    """Average key ops per player-game by day (from daily prev-day counters)."""
    keys = [
        ("ops_water_prev", "WATER"),
        ("ops_feed_prev", "FEED"),
        ("ops_care_prev", "CARE"),
        ("ops_harvest_prev", "HARVEST"),
        ("ops_plant_prev", "PLANT"),
        ("ops_move_prev", "MOVE"),
        ("ops_pass_prev", "PASS"),
    ]
    sums: dict[str, dict[int, float]] = {name: defaultdict(float) for _, name in keys}
    counts: dict[int, int] = defaultdict(int)

    for row in corpus.get("daily") or []:
        day = int(row["day"])
        if day <= 0:
            continue
        # These fields count previous day activity, stored on day D snapshot.
        prev = day - 1
        counts[prev] += 1
        for col, name in keys:
            if col in row:
                sums[name][prev] += float(row.get(col) or 0)

    fig, ax = plt.subplots(figsize=(11, 5.5))
    days = sorted(counts)
    if not days:
        ax.text(0.5, 0.5, "No daily op data", ha="center")
        return _save(fig, out / "ops_by_day.png")

    for name in ("WATER", "FEED", "CARE", "HARVEST", "PLANT", "MOVE", "PASS"):
        ys = [sums[name][d] / max(1, counts[d]) for d in days]
        ax.plot(days, ys, linewidth=2, label=name)

    ax.set_title("Average unit actions per day")
    ax.set_xlabel("Day")
    ax.set_ylabel("Actions / player-game")
    ax.legend(ncol=4, fontsize=8)
    ax.grid(True, alpha=0.25)
    return _save(fig, out / "ops_by_day.png")


def plot_board_occupancy(corpus: dict[str, Any], out: Path) -> Path:
    by_day = defaultdict(lambda: {"plants": [], "animals": [], "weeds": []})
    for row in corpus.get("daily") or []:
        if int(row.get("hour") or 0) != 0:
            continue
        day = int(row["day"])
        by_day[day]["plants"].append(float(row.get("plants") or 0))
        by_day[day]["animals"].append(float(row.get("animals") or 0))
        by_day[day]["weeds"].append(float(row.get("weeds") or 0))

    days = sorted(by_day)
    fig, ax = plt.subplots(figsize=(10, 5.5))
    if not days:
        ax.text(0.5, 0.5, "No board data", ha="center")
        return _save(fig, out / "board_occupancy.png")

    for key, color in (("plants", "#2e8b57"), ("animals", "#4ea8de"), ("weeds", "#6c757d")):
        means = [float(np.mean(by_day[d][key])) for d in days]
        ax.plot(days, means, color=color, linewidth=2.2, label=key)

    ax.set_title("Average board occupancy over season")
    ax.set_xlabel("Day")
    ax.set_ylabel("Tile count")
    ax.legend()
    ax.grid(True, alpha=0.25)
    return _save(fig, out / "board_occupancy.png")


def plot_market_prices(corpus: dict[str, Any], out: Path) -> Path:
    """Mean market prices by day from hourly samples."""
    products = ["wheat", "melon", "strawberry", "milk", "wool", "egg", "fertilizer"]
    sums: dict[str, dict[int, float]] = {p: defaultdict(float) for p in products}
    counts: dict[str, dict[int, int]] = {p: defaultdict(int) for p in products}

    for row in corpus.get("hourly") or []:
        day = int(row["day"])
        # Sample a few hours/day to reduce weight bias.
        if int(row.get("hour") or 0) not in (0, 12):
            continue
        for p in products:
            val = row.get(f"price_{p}")
            if val is None:
                continue
            sums[p][day] += float(val)
            counts[p][day] += 1

    fig, ax = plt.subplots(figsize=(11, 5.5))
    plotted = False
    for p in products:
        days = sorted(counts[p])
        if not days:
            continue
        ys = [sums[p][d] / max(1, counts[p][d]) for d in days]
        label = p.upper()
        ax.plot(days, ys, linewidth=2, label=label, color=PRODUCT_COLORS.get(label, None))
        plotted = True

    if not plotted:
        ax.text(0.5, 0.5, "No price data", ha="center")
    ax.set_title("Average market prices over season")
    ax.set_xlabel("Day")
    ax.set_ylabel("Price")
    ax.legend(ncol=4, fontsize=8)
    ax.grid(True, alpha=0.25)
    return _save(fig, out / "market_prices.png")


def plot_score_scatter(corpus: dict[str, Any], out: Path) -> Path:
    fig, ax = plt.subplots(figsize=(7, 7))
    xs, ys = [], []
    for e in corpus.get("episodes") or []:
        xs.append(float(e["reward0"]))
        ys.append(float(e["reward1"]))
        ax.scatter(e["reward0"], e["reward1"], s=36, color="#1d3557", alpha=0.75)
    if xs:
        lo = min(min(xs), min(ys)) * 0.95
        hi = max(max(xs), max(ys)) * 1.02
        ax.plot([lo, hi], [lo, hi], linestyle="--", color="#adb5bd", label="tie line")
        ax.set_xlim(lo, hi)
        ax.set_ylim(lo, hi)
    ax.set_xlabel("Player 0 final money")
    ax.set_ylabel("Player 1 final money")
    ax.set_title("Episode score scatter")
    ax.legend()
    ax.grid(True, alpha=0.25)
    return _save(fig, out / "score_scatter.png")


def plot_showcase_episode(corpus: dict[str, Any], out: Path, episode_id: str | None = None) -> list[Path]:
    eid = _pick_showcase_episode(corpus, episode_id)
    if not eid:
        return []

    written: list[Path] = []
    # Money + occupancy for both players.
    daily = [r for r in (corpus.get("daily") or []) if str(r["episode_id"]) == eid and int(r.get("hour") or 0) == 0]
    hourly = [r for r in (corpus.get("hourly") or []) if str(r["episode_id"]) == eid]
    agents = {}
    for r in daily:
        agents[int(r["player"])] = r.get("agent")

    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    for pid, color in ((0, "#1d4e89"), (1, "#e76f51")):
        pts = sorted(
            [(int(r["day"]), float(r["money"])) for r in daily if int(r["player"]) == pid]
        )
        if pts:
            axes[0].plot(
                [p[0] for p in pts], [p[1] for p in pts],
                color=color, linewidth=2.3, label=f"P{pid} {agents.get(pid, '')}",
            )
        plants = sorted(
            [(int(r["day"]), float(r.get("plants") or 0)) for r in daily if int(r["player"]) == pid]
        )
        animals = sorted(
            [(int(r["day"]), float(r.get("animals") or 0)) for r in daily if int(r["player"]) == pid]
        )
        if plants:
            axes[1].plot([p[0] for p in plants], [p[1] for p in plants], color=color, linestyle="-", label=f"P{pid} plants")
        if animals:
            axes[1].plot([p[0] for p in animals], [p[1] for p in animals], color=color, linestyle="--", label=f"P{pid} animals")

    axes[0].set_ylabel("Money")
    axes[0].set_title(f"Showcase episode {eid}")
    axes[0].legend()
    axes[0].grid(True, alpha=0.25)
    axes[1].set_xlabel("Day")
    axes[1].set_ylabel("Board count")
    axes[1].legend(ncol=2, fontsize=8)
    axes[1].grid(True, alpha=0.25)
    written.append(_save(fig, out / f"episode_{eid}_economy.png"))

    # Action heatmap-like stacked area from hourly for player 0.
    fig2, ax2 = plt.subplots(figsize=(11, 5))
    p0 = [r for r in hourly if int(r["player"]) == 0]
    if p0:
        # Aggregate to day totals.
        day_ops: dict[int, Counter] = defaultdict(Counter)
        for r in p0:
            d = int(r["day"])
            for key in ("water", "feed", "care", "harvest", "plant", "move", "pass"):
                day_ops[d][key] += int(r.get(key) or 0)
        days = sorted(day_ops)
        stack_keys = ["water", "feed", "care", "harvest", "plant", "move", "pass"]
        stack = np.array([[day_ops[d][k] for d in days] for k in stack_keys])
        ax2.stackplot(days, stack, labels=stack_keys, alpha=0.9)
        ax2.legend(loc="upper left", ncol=4, fontsize=8)
        ax2.set_title(f"Episode {eid} — P0 daily action stack")
        ax2.set_xlabel("Day")
        ax2.set_ylabel("Unit actions")
        ax2.grid(True, alpha=0.2)
    else:
        ax2.text(0.5, 0.5, "No hourly data", ha="center")
    written.append(_save(fig2, out / f"episode_{eid}_actions.png"))

    # Sell events timeline from market orders.
    markets = [r for r in (corpus.get("market_orders") or []) if str(r["episode_id"]) == eid and r.get("op") == "SELL"]
    fig3, ax3 = plt.subplots(figsize=(11, 5))
    if markets:
        for pid, color in ((0, "#1d4e89"), (1, "#e76f51")):
            rows = [r for r in markets if int(r["player"]) == pid]
            if not rows:
                continue
            xs = [int(r["day"]) + int(r["hour"]) / 24.0 for r in rows]
            ys = [float(r.get("revenue") or 0) for r in rows]
            ax3.scatter(xs, ys, s=18, alpha=0.55, color=color, label=f"P{pid} sells")
        ax3.set_title(f"Episode {eid} — sell revenue events")
        ax3.set_xlabel("Day")
        ax3.set_ylabel("Sell revenue (order)")
        ax3.legend()
        ax3.grid(True, alpha=0.25)
    else:
        ax3.text(0.5, 0.5, "No sell events", ha="center")
    written.append(_save(fig3, out / f"episode_{eid}_sells.png"))

    return written


def generate_plots(
    corpus: dict[str, Any],
    out_dir: Path | str,
    *,
    episode_id: str | None = None,
    top_n: int = 12,
) -> list[Path]:
    out = Path(out_dir) / "plots"
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    paths.append(plot_money_curves(corpus, out))
    paths.append(plot_agents(corpus, out, top_n=top_n))
    paths.append(plot_strategies(corpus, out, top_n=top_n))
    paths.append(plot_revenue_mix(corpus, out))
    paths.append(plot_action_mix(corpus, out))
    paths.append(plot_ops_by_day(corpus, out))
    paths.append(plot_board_occupancy(corpus, out))
    paths.append(plot_market_prices(corpus, out))
    paths.append(plot_score_scatter(corpus, out))
    paths.extend(plot_showcase_episode(corpus, out, episode_id=episode_id))
    return paths
