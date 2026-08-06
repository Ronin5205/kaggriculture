# Replay Analyzer

Offline toolkit for mining Kaggriculture Kaggle episode replays: per-player stats, full action logs, strategy tags, corpus tables, and matplotlib charts.

## Quick start

```bash
# Place episode JSON files in replays/
# (e.g. kaggle competitions replay <EPISODE_ID> -p ./replays)

pip install matplotlib numpy   # stdlib otherwise

python analyze_replays.py
```

Defaults:

- Input: `replays/*.json`
- Output: `analysis_out/`
- Plots: on (`analysis_out/plots/`)
- Action + market logs: on (large CSVs)

### Common commands

```bash
# Full corpus
python analyze_replays.py --verbose

# One episode + custom showcase plots
python analyze_replays.py --episode 90503598 --plot-episode 90503598

# Filter exported player / action / market rows to one agent
python analyze_replays.py --agent "Mohit Rao"

# Faster / smaller run
python analyze_replays.py --no-actions --no-hourly --no-plots

# Parallel extract (optional)
python analyze_replays.py --jobs 4
```

### CLI flags

| Flag | Default | Meaning |
|------|---------|---------|
| `--replays DIR` | `replays` | Replay JSON directory |
| `--out DIR` | `analysis_out` | Output directory |
| `--episode ID` | — | Only this episode id / filename stem |
| `--agent NAME` | — | Substring filter on exported agent rows |
| `--jobs N` | `1` | Process-pool workers |
| `--no-daily` | off | Skip daily board snapshots |
| `--no-hourly` | off | Skip per-turn hourly timeseries |
| `--no-actions` | off | Skip `actions.csv` / `market_orders.csv` |
| `--no-plots` | off | Skip matplotlib plots |
| `--plot-episode ID` | top-scoring episode | Showcase episode for detailed plots |
| `--raw` | off | Also write slim `episodes_raw.json` |
| `--verbose` | off | Per-file progress |
| `--top N` | `10` | Console summary rows |

`analysis_out/` is gitignored (generated artifacts).

---

## Layout

```
analyze_replays.py          # CLI entrypoint
analysis/
  load.py                   # discover + load replay JSON
  extract.py                # per-player stats, action/market logs, daily/hourly
  strategies.py             # rule-based strategy tags
  aggregate.py              # corpus tables
  report.py                 # CSV / JSON writers + console summary
  visualize.py              # matplotlib plots
```

Pipeline:

```text
replays/*.json
    → load one episode
    → extract per player (stats + logs + timeseries)
    → label strategies
    → aggregate corpus
    → write CSVs / JSON
    → generate plots
```

Episodes are processed **one file at a time** (or in a process pool). Only summaries / flattened rows are kept for aggregation, so the ~30MB × N replay corpus stays manageable.

---

## Replay schema (what we read)

Each file is a Kaggle `env.toJSON()` dump:

| Field | Use |
|-------|-----|
| `info.EpisodeId`, `info.Agents`, `info.seed` | Identity |
| `rewards`, `statuses` | Final scores |
| `configuration.turnsPerDay` | Day/hour indexing (default 24) |
| `steps[t][player]` | `action` + `observation` |

Important details:

- Both players’ `private` state is present in these dumps (shed, seeds, inventories).
- The `action` on step `t` matches the post-action observation at `t` (step `0` is the initial state; first real spend usually appears at step `1`).
- Unit ops live under `action.farmer` and `action.hands[]`; market ops under `action.market[]`.

---

## What gets extracted

### Per player-game summary

- Outcome: final money, margin, win/loss/tie, opponent
- Opening fingerprint (first non-empty market order list)
- Buys: seeds, animals, products, land, hires
- Plants / animal placements / builds
- Sells: qty, estimated revenue (`qty × price` at sell step), avg sell price
- Timing: first plant / animal / sell day; quadrant unlock days
- Action mix: move / field / pass percentages; key op counts
- Peaks: plants, animals, weeds, hands
- Wheat grown vs bought proxy
- Strategy tags (multi-label)

### Action log (`actions.csv`)

One row per unit action (farmer + each hand), every turn:

`episode_id, player, agent, step, day, hour, unit, op, arg0, arg1, arg2, x, y, money, n_hands`

Example: `unit=hand2`, `op=FEED`, position from the farm-hand list after the step.

### Market log (`market_orders.csv`)

One row per market order:

`episode_id, player, agent, step, day, hour, order_i, op, item, qty, price, revenue, money, market_inv`

### Daily timeseries (`daily.csv`)

Sampled at hour `0` each day (plus final step if needed):

- Money, hands, unlocked quadrants
- Board occupancy (plants / animals / weeds / per-crop / per-animal)
- Cumulative sell revenue; previous-day sell qty by product
- Previous-day unit-op totals (water, feed, care, harvest, plant, move, pass)

### Hourly timeseries (`hourly.csv`)

One row per turn:

- Money + delta, hands, cum sell revenue
- That turn’s unit-op counts (move/field/pass/water/feed/…)
- Market prices for key products
- Board occupancy sampled every 6 hours (and day boundaries)

---

## Strategy tags

Defined in `analysis/strategies.py`. Tags are **multi-label** and tuned to current leaderboard meta (heavy hire, sheep/cow open, berry + dairy). Thresholds are heuristics — adjust there if the meta shifts.

| Tag family | Examples | Signal |
|------------|----------|--------|
| Opening | `animal_open`, `melon_rush`, `melon_lite`, `hire_open_5`, `hire_open_7` | Day-0 market orders |
| Board intensity | `animal_core`, `animal_max`, `hire_max`, `hire_ultra` | Peak animals / median daily hires |
| Land | `land_early`, `land_mid`, `land_none` | 2nd quadrant unlock day |
| Crops | `berry_plant_heavy`, `melon_plant_heavy`, `tomato_line`, `wheat_buyer` | Plant / buy mix |
| Care / fert | `animal_care_heavy`, `animal_care_ultra`, `fert_seller` | CARE / fertilizer sells |
| Revenue engine | `primary_dairy`, `dairy_focus`, `berry_engine`, `wool_focus`, `melon_focus`, `*_support` | Sell-revenue shares |

Corpus tables `strategies.csv` and the console summary rank tags by average final money and win rate.

---

## Outputs

Written under `analysis_out/` (unless `--out` changes it):

| File | Contents |
|------|----------|
| `episodes.csv` | Scoreline per episode |
| `players.csv` | Flattened per-player features + strategy string |
| `agents.csv` | Win rate / avg money by agent name |
| `strategies.csv` | Tag frequency and performance |
| `openings.csv` | Opening-book fingerprints |
| `op_counts.csv` | Corpus unit-action tallies |
| `market_op_counts.csv` | Corpus market-op tallies |
| `daily.csv` | Day-level timeseries |
| `hourly.csv` | Turn-level timeseries |
| `actions.csv` | Full unit action log (large) |
| `market_orders.csv` | Full market order log |
| `corpus_summary.json` | Compact top-line JSON |
| `episodes_raw.json` | Slim per-episode JSON (`--raw`) |
| `plots/*.png` | Charts |

Rough sizes on the current 27-replay corpus:

- `actions.csv` ≈ 23MB (~377k rows)
- `hourly.csv` ≈ 5MB (~39k rows)
- `market_orders.csv` ≈ 3MB (~49k rows)

Use `--no-actions` / `--no-hourly` when you only need summary tables.

---

## Plots

Generated by `analysis/visualize.py` into `analysis_out/plots/`:

| Plot | Description |
|------|-------------|
| `money_curves.png` | All player-game money curves + corpus mean / IQR |
| `agents_avg_money.png` | Top agents by average final money |
| `strategies_avg_money.png` | Strategy tags by average money |
| `revenue_mix.png` | Corpus sell-revenue pie |
| `action_mix.png` | Unit-action histogram (moves collapsed) |
| `ops_by_day.png` | Average water/feed/care/harvest/… by day |
| `board_occupancy.png` | Mean plants / animals / weeds over season |
| `market_prices.png` | Mean product prices over season |
| `score_scatter.png` | Player0 vs player1 final scores |
| `episode_<id>_economy.png` | Showcase: money + board occupancy |
| `episode_<id>_actions.png` | Showcase: P0 daily action stack |
| `episode_<id>_sells.png` | Showcase: sell revenue events |

Showcase episode defaults to the highest-scoring game in the run; override with `--plot-episode`.

Requires `matplotlib` and `numpy` (Agg backend; no display needed).

---

## Interpreting results

Typical workflow:

1. Run the analyzer on your `replays/` folder.
2. Skim console summary + `agents.csv` / `openings.csv` for meta.
3. Use `players.csv` + `strategies.csv` to see which midgame tags correlate with score.
4. Drill into `actions.csv` / `market_orders.csv` / `hourly.csv` for a specific `episode_id` + `player`.
5. Open `plots/` for trends; use showcase plots for a close game.

Notes / caveats:

- Sell revenue is approximated with the **market price observed on the sell step** (good for ranking product mix; not a perfect cashflow audit).
- Wheat “grown vs bought” uses plant counts vs `BUY_SEED`/`BUY_PRODUCT` wheat — a proxy, not harvested yield.
- Strategy thresholds were calibrated on a homogeneous top-agent corpus; many games share the same opening, so **revenue-share tags** usually separate agents better than opening tags alone.
- `--agent` filters **exported** player/daily/hourly/action/market rows; agent/strategy leaderboards remain corpus-wide unless you re-run on a filtered set of episodes.

---

## Extending

| Goal | Where to edit |
|------|----------------|
| New summary columns | `extract.py` → `aggregate._flat_player_row` |
| New strategy tags | `strategies.py` |
| New CSV / JSON artifacts | `report.py` |
| New charts | `visualize.generate_plots` |
| Replay discovery / schema helpers | `load.py` |

Keep extractors streaming (one episode at a time). Prefer daily/hourly aggregates for trends; keep full action logs optional behind `--no-actions` when experimenting.
