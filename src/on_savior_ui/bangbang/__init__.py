"""Bang-bang burn planning: data (sensor/ship readout) vs. intent (burn profile).

See :mod:`on_savior_ui.bangbang.model` for the physics and dataclasses, and
run the Streamlit front-end with ``uv run on-savior-ui bangbang``.
"""

from .economics import CostBreakdown, EconomicsRates, estimate_cost
from .model import (
    G0,
    BurnPhase,
    BurnPlan,
    Intent,
    ShipData,
    TargetData,
    plan_burn,
)
from .trajectory import ClosestApproach, TrajectoryPoint, build_trajectory

__all__ = [
    "G0",
    "BurnPhase",
    "BurnPlan",
    "ClosestApproach",
    "CostBreakdown",
    "EconomicsRates",
    "Intent",
    "ShipData",
    "TargetData",
    "TrajectoryPoint",
    "build_trajectory",
    "estimate_cost",
    "plan_burn",
]
