"""Cost estimate for a burn plan: license time, propellant, life support.

Pure post-processing over a :class:`~on_savior_ui.bangbang.model.BurnPlan` —
nothing here feeds back into the physics in :mod:`.model`. Rates are
business/logistics inputs (what the license costs per day, what propellant
and O2 cost per kg) — not sensor data and not burn intent, so they get their
own small dataclass rather than joining either ``ShipData``/``TargetData``
or ``Intent``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .model import G0, BurnPlan, ShipData

SECONDS_PER_DAY = 86400.0


@dataclass
class EconomicsRates:
    """Rates for costing a burn. All pilot/business input — nothing here comes from a save."""

    license_cost_per_day: float = 5000.0
    fuel_cost_per_kg: float = 20.0
    crew_count: int = 1
    o2_cost_per_kg: float = 5.0
    o2_kg_per_crew_per_day: float = 0.84  # typical adult metabolic O2 consumption
    isp_s: float | None = None  # for delta-v -> propellant mass; falls back to ship.isp_s


@dataclass
class CostBreakdown:
    duration_days: float
    license_cost: float
    life_support_cost: float
    propellant_mass_kg: float | None
    fuel_cost: float | None
    total_cost: float
    warnings: list[str] = field(default_factory=list)


def estimate_cost(plan: BurnPlan, ship: ShipData, rates: EconomicsRates) -> CostBreakdown:
    warnings: list[str] = []
    duration_days = plan.total_time_s / SECONDS_PER_DAY
    license_cost = rates.license_cost_per_day * duration_days
    life_support_cost = rates.crew_count * rates.o2_kg_per_crew_per_day * duration_days * rates.o2_cost_per_kg

    isp = rates.isp_s if rates.isp_s is not None else ship.isp_s
    propellant_mass_kg: float | None = None
    fuel_cost: float | None = None
    if isp and isp > 0 and ship.wet_mass_kg > 0:
        # Tsiolkovsky: mass burned for this dv, off the ship's current (wet) mass.
        propellant_mass_kg = ship.wet_mass_kg * (1 - math.exp(-plan.dv_total_ms / (isp * G0)))
        fuel_cost = propellant_mass_kg * rates.fuel_cost_per_kg
    else:
        warnings.append(
            "no Isp available to convert delta-v into propellant mass — fuel cost excluded from the total"
        )

    total_cost = license_cost + life_support_cost + (fuel_cost or 0.0)

    return CostBreakdown(
        duration_days=duration_days,
        license_cost=license_cost,
        life_support_cost=life_support_cost,
        propellant_mass_kg=propellant_mass_kg,
        fuel_cost=fuel_cost,
        total_cost=total_cost,
        warnings=warnings,
    )
