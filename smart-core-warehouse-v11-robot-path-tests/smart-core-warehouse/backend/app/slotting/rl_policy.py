from __future__ import annotations

from app.core.models import Slot


def placement_policy_value(slot: Slot, demand_score: float) -> float:
    """Return a learned-policy style value for placing a box in this slot.

    The competition demo does not train online during operation. Instead this is
    a compact reinforcement-learning policy surrogate: it evaluates the reward
    the agent would receive for lower travel time, good accessibility, rack
    balance, and future retrieval speed for high-demand cores.
    """
    travel_reward = max(0.0, 1.0 - float(slot.travel_cost) / 10.0)
    access_reward = max(0.0, min(1.0, float(slot.accessibility_score)))
    rack_balance_reward = 1.0 - min(abs(float(slot.rack_face or 1) - 2.5) / 2.5, 1.0)
    future_reward = travel_reward * max(0.0, min(1.0, float(demand_score)))
    value = (
        0.40 * travel_reward
        + 0.25 * access_reward
        + 0.20 * future_reward
        + 0.15 * rack_balance_reward
    )
    return round(max(0.0, min(1.0, value)), 4)

