"""Melon–Dairy Compound agent — two-wave melons + CARE dairy + metered sells."""

from .state_tile import analyze_farm
from .market_policy import build_market_orders
from .tasks import build_tasks, assign_unit_action


def agent(obs):
    """
    Observation → action dict.

    Strategy: 12→24 watered melons, scale to ~10 CARE'd cows, metered sells,
    late wheat short-cycle, endgame shed cashout. Pastures near shed; crops out.
    """
    if not isinstance(obs, dict):
        try:
            obs = dict(obs)
        except Exception:
            pass

    player = obs.get("player", 0)
    farms = obs.get("farms") or []
    if not farms or player >= len(farms):
        return {"farmer": ["PASS"], "hands": [], "market": []}

    me = farms[player]
    private = obs.get("private") or {}
    summary = analyze_farm(me, current_day=obs.get("day"))

    market = build_market_orders(obs, summary)

    claimed = set()
    tasks = build_tasks(obs, summary, claimed)

    farmer_pos = tuple(me.get("farmer") or [0, 0])
    inventories = list(private.get("inventories") or [{}])
    farmer_inv = inventories[0] if inventories else {}

    farmer_op = assign_unit_action(
        farmer_pos, farmer_inv, obs, summary, tasks, claimed
    )

    hands_ops = []
    for i, hand in enumerate(me.get("hands") or []):
        hpos = tuple(hand)
        hinv = inventories[i + 1] if i + 1 < len(inventories) else {}
        hands_ops.append(
            assign_unit_action(hpos, hinv, obs, summary, tasks, claimed)
        )

    def _norm(op):
        if op is None:
            return ["PASS"]
        if isinstance(op, str):
            return [op]
        return list(op)

    return {
        "farmer": _norm(farmer_op),
        "hands": [_norm(h) for h in hands_ops],
        "market": market,
    }
