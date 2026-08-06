# Strategy: Goose Egg Engine (Day-30 Bank Max)

Agent entry point: `agent.agent` (also re-exported from `main.py`).

Goal: maximize **bank balance** at the end of day 30 (turn 720). Unsold shed
inventory does **not** count, so the agent liquidates before season end.

## Why this strategy

| Option | Yield / tile / day | Price resilience | Notes |
|--------|-------------------:|------------------|-------|
| Wheat | 0.80 | Strong (glut → ~$19–20) | Cheap bootstrap + animal feed |
| Carrot | 0.75 | Weak (glut → $1) | Fast cash but crashes |
| Goose / Egg | **1.00** (+ CARE ≈ 2.00) | Strong (glut → ~$39–40) | Best sustained income |
| Cow / Milk | 0.50 | Crashes to $1 | Avoid as primary |
| Melon / Wool | high $ base | Crash to $1 easily | Optional drip-sell only |

Geese win on sustained output. Eggs absorb oversupply (`MARKET_PARAMS["EGG"]`
uses a mild `log` above-curve). Wheat funds the early game and feeds the flock.

`CARE` banks +1 per fed-and-cared day and pays out on the next production tick.
For daily geese that is roughly **2 eggs/day/goose** in steady state — roughly
doubling revenue versus feed-only.

## Phases

### Days 0–3 — Bootstrap (wheat only)

1. Hire cheap farm hands (Fibonacci costs `1, 1, 2, 3, …` reset daily).
2. Buy wheat seeds and fill empty tiles.
3. **Water every plant every day** — new seeds start at
   `consecutive_unwatered = 1`; skipping the plant day weeds them overnight.
4. Harvest wheat at `max_yield_day` (age 4) for peak units; keep a feed buffer,
   sell the rest.
5. No livestock yet — wait until day 4 so the first wheat cycle can fund feed.

### Days 4–20 — Scale the egg engine

1. Build **at most one empty coop ahead** of the current flock (targets scale
   with unlocked quadrants: 6 / 10 / 14 / 18).
2. Buy a goose only when: empty coop exists, wheat buffer covers the new bird,
   and cash reserve remains.
3. `PICKUP` goose from shed → `PLACE` on coop the same day (end-of-day dump
   returns unplaced animals to the shed).
4. Expand land when tiles are tight and cash is healthy.
5. Apply animal fertilizer to wheat during its watering bonus window.
6. Dig excess empty coops back to dirt so wheat can use the space.

### Days 21–26 — Produce

1. Daily loop per goose: pickup wheat → feed → care → harvest eggs →
   collect fertilizer.
2. Keep wheat cycles running (last plant by day 25).
3. Sell eggs freely; drip-sell any premium goods if price is still decent.

### Days 27–29 — Liquidate

1. Harvest everything remaining.
2. Drop inventories to shed and `SELL` all sellable stock.
3. Stop long-horizon planting / expansion.

## How constants & tile state are used

### From `agent/constants.py` / `engine_rules.py`

- Seed/animal costs, land prices, hire Fibonacci, season length.
- **Engine-accurate** crop windows live in `engine_rules.py` (the live
  interpreter’s `MELON.max_yield_day` is **12**, not the README’s 10).
- Watering bonus window for one-time crops:
  `start = (max_yield_day + 1) // 2` … `max_yield_day`
  (matches `kaggriculture.py` `WATER` handler).
- Premium vs staple product sets drive sell throttling.

### From `agent/state_tile.py`

`analyze_farm(farm, day)` supplies:

- `empty`, `weeds`, `unwatered_plants`, `harvestable_plants`
- `structures_empty` / `structures_occupied`
- `unfed_animals`, `collectible_fertilizer`

The agent turns that scan into a **priority task list**, then greedily assigns
each farmer/hand to the closest feasible task (path via N/S/E/W).

### Action priorities (high → low)

1. Water (especially tiles already at `consecutive_unwatered >= 1`)
2. Pickup wheat → Feed animals
3. Place geese / pickup geese from shed
4. Harvest near-cap animal products
5. Harvest peak wheat
6. Care animals
7. Collect fertilizer / fertilize wheat
8. Build coops / plant wheat / dig weeds
9. Drop sellable inventory at shed access tiles `(4,4),(5,4),(4,5),(5,5)`

Within a priority band, targets are ordered **near the shed first** (snake
within equal distance). Each job goes to the **closest free unit**, and steps
prefer the longer axis — so crews expand outward from spawn instead of
sweeping the top row then walking down.

### Hiring

Hire enough hands to keep the crew busy for ~21 turns (small slack, not a
long idle tail). Crew size is `ceil(today's tile-jobs / (21 × 0.72))`, capped
at farmer+5, with top-ups allowed through hour 3 if backlog still exceeds
capacity. Pathing (near-shed order + closest unit) is what cuts wasted walks;
hiring stays matched to workload.

## Market policy

- **Stock when cheap:** `BUY_PRODUCT WHEAT` while price ≤ $22 toward ~5 days of
  feed; fertilizer when ≤ $70. Always leave ~12 shed slots for harvests.
- **Sell into demand:** hold eggs until an egg shop unlocks (Bakery / Brunch),
  price ≥ $48, day ≥ 12, or shed pressure. Same idea for wheat / premiums.
- **Shed safety:** soft cap ~78 starts pressure sales; hard cap ~92 / wind-down
  forces liquidation so end-of-day drops never discard into a full shed.
- Never sell live animals. Max 10 market orders/turn.

## Important engine details the agent respects

- `FEED` consumes **wheat from the unit’s inventory**, not the shed → must
  `PICKUP WHEAT` first.
- `SELL` only draws from the **shed** → harvest/drop before selling.
- Seeds are not picked up; `PLANT` consumes `private["seeds"]` directly.
- If N units issue `PLANT WHEAT` with fewer than N seeds, **none** plant —
  the agent caps plant tasks by seed count.
- Hands vanish each night and must be re-hired; inventories dump to shed
  (overflow past capacity 100 is discarded).

## Files

| Path | Role |
|------|------|
| `agent/agent.py` | Decision loop |
| `agent/engine_rules.py` | Interpreter-aligned crop/animal/land helpers |
| `agent/state_tile.py` | Tile scan + local simulation helpers |
| `agent/constants.py` | README tables (reference / shared numbers) |
| `main.py` | Re-exports `agent` + local eval harness |

## Local eval (observed)

Against the built-in `starter` agent over 5 seeds: roughly **$8.5k–$13.5k**
bank at day 30 (avg ~$10.7k) vs starter ~$3.5k. Typical late-game flock is
~7–8 geese with 2–3 unlocked quadrants.

```bash
python main.py
# or
python -c "from kaggle_environments import make; from agent import agent; \
env=make('kaggriculture', debug=True); env.run([agent, 'starter']); \
print([(i,s.reward) for i,s in enumerate(env.steps[-1])])"
```
