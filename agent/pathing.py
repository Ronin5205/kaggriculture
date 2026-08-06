"""Movement helpers for the meta farms agent."""

from .constants import SHED_ADJACENT, SHED_CENTER

DIRS = (
    ("NORTH", 0, -1),
    ("SOUTH", 0, 1),
    ("EAST", 1, 0),
    ("WEST", -1, 0),
)


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def shed_dist(pos):
    """Manhattan distance to shed center (4.5, 4.5), using float coords."""
    x, y = pos
    return abs(x - SHED_CENTER[0]) + abs(y - SHED_CENTER[1])


def is_shed_adjacent(pos):
    return tuple(pos) in SHED_ADJACENT


def nearest_shed_tile(pos):
    """Closest of the four shed-adjacent standing tiles."""
    return min(SHED_ADJACENT, key=lambda t: manhattan(pos, t))


def step_toward(pos, target, board_size=10):
    """
    One cardinal step from `pos` toward `target`.
    Returns (op_name,) or ("PASS",) if already there / blocked by board edge.
    """
    x, y = pos
    tx, ty = target
    if (x, y) == (tx, ty):
        return ("PASS",)

    dx, dy = tx - x, ty - y
    # Prefer the axis with larger remaining distance.
    candidates = []
    if abs(dx) >= abs(dy):
        if dx > 0:
            candidates.append(("EAST", 1, 0))
        elif dx < 0:
            candidates.append(("WEST", -1, 0))
        if dy > 0:
            candidates.append(("SOUTH", 0, 1))
        elif dy < 0:
            candidates.append(("NORTH", 0, -1))
    else:
        if dy > 0:
            candidates.append(("SOUTH", 0, 1))
        elif dy < 0:
            candidates.append(("NORTH", 0, -1))
        if dx > 0:
            candidates.append(("EAST", 1, 0))
        elif dx < 0:
            candidates.append(("WEST", -1, 0))

    for name, ox, oy in candidates:
        nx, ny = x + ox, y + oy
        if 0 <= nx < board_size and 0 <= ny < board_size:
            return (name,)
    return ("PASS",)


def nearest_pos(origin, positions):
    """Return the position in `positions` closest to `origin`, or None."""
    if not positions:
        return None
    return min(positions, key=lambda p: manhattan(origin, p))


def sort_by_shed_near(positions):
    """Ascending distance to shed (pasture preference)."""
    return sorted(positions, key=shed_dist)


def sort_by_shed_far(positions):
    """Descending distance to shed (crop preference)."""
    return sorted(positions, key=shed_dist, reverse=True)


def plantable_empties(empty, reserve_near_for_pastures=0):
    """
    Empties eligible for planting: not shed-adjacent, optionally excluding
    the N nearest tiles reserved for upcoming pastures.
    """
    candidates = [p for p in empty if not is_shed_adjacent(p)]
    if reserve_near_for_pastures <= 0:
        return sort_by_shed_far(candidates)
    near = sort_by_shed_near(candidates)
    reserved = set(near[:reserve_near_for_pastures])
    plantable = [p for p in candidates if p not in reserved]
    return sort_by_shed_far(plantable)


def pasture_empties(empty):
    """Empties eligible for BUILD_PASTURE: not shed-adjacent, nearest first."""
    return sort_by_shed_near([p for p in empty if not is_shed_adjacent(p)])
