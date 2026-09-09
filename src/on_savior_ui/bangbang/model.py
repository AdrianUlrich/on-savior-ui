"""Bang-bang burn planning: how hard and how long to burn to close on a target.

Split in two halves, matching what a flight-management computer could and
couldn't tell you:

- :class:`ShipData` / :class:`TargetData` — everything a sensor suite and the
  ship's own performance readout could plausibly hand you: mass, thrust,
  delta-v budget, and the target's range, closing rate, cross-track rate, and
  ETA. These are built by hand today; :mod:`on_savior_ui.bangbang.save_bridge`
  will eventually populate them from a save, so the numbers shown here never
  exceed what the in-fiction instruments could measure — no reading the
  target's true state.
- :class:`Intent` — the burn *profile* you want: how conservative, what
  arrival speed and G-limit you're willing to accept, and — competing with
  each other — a desired arrival time, a fixed coast (e.g. to fit a sleep
  shift), and/or a speed cap. None of this is observable from a save; it's
  pilot preference with sane defaults.

:func:`plan_burn` turns both into a :class:`BurnPlan`: burn/coast phase
durations, delta-v spent, peak acceleration, and a feasibility verdict
against the ship's real limits.

Scope note: this models the standard single-switch **accelerate, (optionally
coast,) decelerate** profile — burn toward the target, flip, burn to kill
the closing rate — which is what "bang-bang" means in the Ostranauts
community and covers the normal approach case. It does not attempt the
general (possibly decelerate-first) minimum-time control problem; if the
geometry needs that, :func:`plan_burn` reports infeasible rather than
guessing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

G0 = 9.80665  # standard gravity, m/s^2 — for converting "preferred G" to acceleration

Preset = Literal["aggressive", "standard", "conservative"]
PhaseKind = Literal["burn_prograde", "coast", "burn_retro"]


# --------------------------------------------------------------------------
# Data: what a flight-management computer could plausibly show
# --------------------------------------------------------------------------


@dataclass
class ShipData:
    """Ship capability, as read off the ship's own systems.

    ``delta_v_available_ms`` is the direct reading, if the ship reports one.
    If it doesn't, supply ``dry_mass_kg`` and ``isp_s`` instead and it will be
    derived via the rocket equation.
    """

    name: str = ""
    wet_mass_kg: float = 0.0
    max_thrust_N: float = 0.0
    delta_v_available_ms: float | None = None
    dry_mass_kg: float | None = None
    isp_s: float | None = None
    sensor_notes: str = ""

    def available_delta_v_ms(self) -> float | None:
        if self.delta_v_available_ms is not None:
            return self.delta_v_available_ms
        if (
            self.isp_s
            and self.dry_mass_kg
            and self.dry_mass_kg > 0
            and self.wet_mass_kg > self.dry_mass_kg
        ):
            return self.isp_s * G0 * math.log(self.wet_mass_kg / self.dry_mass_kg)
        return None


@dataclass
class TargetData:
    """The target track, as read off sensors.

    Sign convention: ``closing_speed_ms`` is positive when the range is
    shrinking on its own (no burn), negative when it's opening (target
    receding). ``cross_speed_ms`` is signed too: positive means the target
    is drifting to the right of your original heading (clockwise, viewed
    from above), negative to the left. Left unopposed (see
    ``Intent.null_cross_track``) this is what determines which side a burn
    misses on — see :mod:`.trajectory`.

    ``eta_s`` is the flight computer's own **inertial** projection — time to
    zero range if the current closing speed simply persists, with no burn.
    It's naively overdetermined against range/closing_speed (and can disagree
    with the value either implies, since each is measured independently) but
    it is not a plan: :func:`plan_burn` never reads it. A *desired* arrival
    time is pilot intent — see ``Intent.desired_eta_s``.
    """

    name: str = ""
    distance_m: float = 0.0
    closing_speed_ms: float = 0.0
    cross_speed_ms: float = 0.0
    eta_s: float | None = None
    # TBD: sensor precision modeling — not consumed by plan_burn yet.
    distance_uncertainty_frac: float | None = None
    speed_uncertainty_ms: float | None = None


# --------------------------------------------------------------------------
# Intent: the desired burn profile — never loadable from a save
# --------------------------------------------------------------------------


@dataclass
class Intent:
    """Pilot intent for the burn. Not derivable from a save; has good defaults.

    Three fields compete to shape the *schedule* — how the distance gets
    split between burning and coasting — and are resolved by precedence
    (see :func:`plan_burn`):

    - ``fixed_coast_s`` — a hard commitment to coast this long (e.g. to fit a
      sleep shift). Wins outright over ``desired_eta_s`` when both are set.
    - ``desired_eta_s`` — a soft target arrival time; met if reachable, else
      relaxed to the minimum-time profile with a warning.
    - Neither set — minimum time: burn hardest allowed the whole way.

    ``max_speed_ms`` is a separate, always-hard cap (a local speed limit or
    other precaution) applied on top of whichever schedule above produced
    the burn. When it only affects the minimum-time schedule it is resolved
    automatically (burn to the cap, coast at the cap, decelerate); against an
    explicit ``fixed_coast_s`` or ``desired_eta_s`` commitment a violation is
    reported as infeasible instead of silently overridden, since satisfying
    both an exact schedule and a speed cap can require a different burn
    shape than either alone.
    """

    arrival_speed_ms: float = 0.0
    null_cross_track: bool = False
    preferred_accel_g: float | None = 0.3
    thrust_margin_frac: float = 0.15
    dv_margin_frac: float = 0.20
    desired_eta_s: float | None = None
    fixed_coast_s: float | None = None
    max_speed_ms: float | None = None

    @classmethod
    def preset(cls, name: Preset) -> "Intent":
        presets: dict[Preset, "Intent"] = {
            "aggressive": cls(preferred_accel_g=0.6, thrust_margin_frac=0.05, dv_margin_frac=0.10),
            "standard": cls(),
            "conservative": cls(preferred_accel_g=0.2, thrust_margin_frac=0.25, dv_margin_frac=0.30),
        }
        try:
            return presets[name]
        except KeyError:
            raise ValueError(f"unknown preset {name!r}; choose from {sorted(presets)}") from None


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


@dataclass
class BurnPhase:
    kind: PhaseKind
    duration_s: float
    delta_v_ms: float


@dataclass
class BurnPlan:
    feasible: bool
    warnings: list[str] = field(default_factory=list)
    mode: Literal["minimum_time", "desired_eta", "fixed_coast"] = "minimum_time"
    speed_capped: bool = False
    accel_used_ms2: float = 0.0
    accel_used_g: float = 0.0
    phases: list[BurnPhase] = field(default_factory=list)
    total_time_s: float = 0.0
    turnover_speed_ms: float = 0.0
    dv_longitudinal_ms: float = 0.0
    dv_cross_ms: float = 0.0
    dv_total_ms: float = 0.0
    dv_available_ms: float | None = None
    dv_budget_ms: float | None = None
    dv_margin_ms: float | None = None


# --------------------------------------------------------------------------
# Physics
# --------------------------------------------------------------------------


def _real_roots(a: float, b: float, c: float) -> list[float]:
    if abs(a) < 1e-12:
        return [] if abs(b) < 1e-12 else [-c / b]
    disc = b * b - 4 * a * c
    if disc < 0:
        return []
    if disc == 0:
        return [-b / (2 * a)]
    sq = math.sqrt(disc)
    return [(-b - sq) / (2 * a), (-b + sq) / (2 * a)]


def _two_phase(a: float, v0: float, vf: float, d: float) -> tuple[float, float] | None:
    """Minimum-time accelerate-then-decelerate burn. Returns (t1, t2).

    Derivation: with phase 1 at +a for t1 (closing speed v0 -> v1) and phase 2
    at -a for t2 (v1 -> vf), eliminate t2 = t1 + k with k = (v0 - vf) / a,
    then match distance covered to d:

        a*t1^2 + 2*v0*t1 + (v0*k - a*k^2/2 - d) = 0
    """
    k = (v0 - vf) / a
    roots = _real_roots(a, 2 * v0, v0 * k - 0.5 * a * k * k - d)
    valid = [t1 for t1 in roots if t1 >= -1e-9 and t1 + k >= -1e-9]
    if not valid:
        return None
    t1 = max(0.0, min(valid))
    return t1, max(0.0, t1 + k)


def _three_phase(a: float, v0: float, vf: float, d: float, total_t: float) -> tuple[float, float, float] | None:
    """Accelerate, coast, decelerate to arrive in exactly total_t. Returns (t1, t_coast, t2).

    Same elimination as _two_phase, plus t_coast = total_t - t1 - t2, gives:

        a*t1^2 - a*(total_t - k)*t1 + (d - v0*total_t + a*k^2/2) = 0

    Prefers the smaller valid t1 (shorter burn, longer coast, less delta-v).
    """
    k = (v0 - vf) / a
    roots = _real_roots(a, -a * (total_t - k), d - v0 * total_t + 0.5 * a * k * k)
    best: tuple[float, float, float] | None = None
    for t1 in roots:
        t2 = t1 + k
        t_coast = total_t - t1 - t2
        if t1 >= -1e-9 and t2 >= -1e-9 and t_coast >= -1e-9:
            candidate = (max(0.0, t1), max(0.0, t_coast), max(0.0, t2))
            if best is None or candidate[0] < best[0]:
                best = candidate
    return best


def _fixed_coast(a: float, v0: float, vf: float, d: float, coast_s: float) -> tuple[float, float] | None:
    """Accelerate, coast for exactly coast_s, decelerate. Returns (t1, t2); total time falls out.

    Same elimination as _two_phase (t2 = t1 + k, k = (v0 - vf) / a), with the
    coast folded into the distance equation instead of the (now unknown)
    total time:

        a*t1^2 + (2*v0 + a*coast_s)*t1 + (v0*coast_s + v0*k - a*k^2/2 - d) = 0

    Reduces to the _two_phase equation when coast_s = 0.
    """
    k = (v0 - vf) / a
    roots = _real_roots(a, 2 * v0 + a * coast_s, v0 * coast_s + v0 * k - 0.5 * a * k * k - d)
    valid = [t1 for t1 in roots if t1 >= -1e-9 and t1 + k >= -1e-9]
    if not valid:
        return None
    t1 = max(0.0, min(valid))
    return t1, max(0.0, t1 + k)


def _speed_capped_two_phase(
    a: float, v0: float, vf: float, d: float, v_max: float
) -> tuple[float, float, float] | None:
    """Minimum-time burn subject to a hard cap on closing speed. Returns (t1, t_coast, t2).

    Burn to v_max, coast at v_max for whatever distance is left, decelerate
    from v_max to vf — the fastest way to cover d without exceeding v_max.
    Returns None if v0 or vf themselves already exceed the cap (would need a
    decelerate-first profile, out of scope) or if the cap doesn't actually
    bind (reaching it isn't necessary to cover the distance) — the caller
    should fall back to the unconstrained _two_phase in the latter case.
    """
    if v0 > v_max + 1e-9 or vf > v_max + 1e-9:
        return None
    t1 = (v_max - v0) / a
    t2 = (v_max - vf) / a
    d1 = v0 * t1 + 0.5 * a * t1 * t1
    d3 = v_max * t2 - 0.5 * a * t2 * t2
    d_coast = d - d1 - d3
    if d_coast < -1e-6:
        return None  # cap doesn't bind; unconstrained two-phase never reaches it
    t_coast = d_coast / v_max if v_max > 1e-9 else 0.0
    return t1, max(0.0, t_coast), t2


def plan_burn(ship: ShipData, target: TargetData, intent: Intent | None = None) -> BurnPlan:
    intent = intent or Intent()

    if ship.wet_mass_kg <= 0 or ship.max_thrust_N <= 0:
        raise ValueError("ship wet mass and max thrust must both be positive")

    accel_max = ship.max_thrust_N / ship.wet_mass_kg
    accel_used = accel_max * (1 - intent.thrust_margin_frac)
    if intent.preferred_accel_g is not None:
        accel_used = min(accel_used, intent.preferred_accel_g * G0)

    if accel_used <= 0:
        return BurnPlan(
            feasible=False,
            warnings=["no usable acceleration after margins — raise the thrust margin or preferred G"],
            accel_used_ms2=0.0,
            accel_used_g=0.0,
        )

    v0 = target.closing_speed_ms
    vf = intent.arrival_speed_ms
    d = target.distance_m

    two = _two_phase(accel_used, v0, vf, d)
    if two is None:
        return BurnPlan(
            feasible=False,
            warnings=[
                "no accelerate/flip/decelerate solution exists for this acceleration and geometry — "
                "the target may be receding faster than this burn can catch, or the approach needs "
                "braking before accelerating; re-check the sensor reading"
            ],
            accel_used_ms2=accel_used,
            accel_used_g=accel_used / G0,
        )
    t1, t2 = two
    t_min_total = t1 + t2
    t_coast = 0.0
    total_time = t_min_total
    warnings: list[str] = []
    mode: Literal["minimum_time", "desired_eta", "fixed_coast"] = "minimum_time"

    # --- Schedule: fixed_coast_s beats desired_eta_s beats minimum time. ---
    if intent.fixed_coast_s is not None:
        mode = "fixed_coast"
        if intent.desired_eta_s is not None:
            warnings.append(
                f"fixed coast of {intent.fixed_coast_s:.0f}s overrides the desired ETA of "
                f"{intent.desired_eta_s:.0f}s — desired ETA is ignored"
            )
        fixed = _fixed_coast(accel_used, v0, vf, d, intent.fixed_coast_s)
        if fixed is not None:
            t1, t2 = fixed
            t_coast = intent.fixed_coast_s
            total_time = t1 + t_coast + t2
            if intent.desired_eta_s is not None:
                delta = total_time - intent.desired_eta_s
                warnings.append(f"resulting arrival is {total_time:.0f}s ({delta:+.0f}s vs. desired)")
        else:
            warnings.append(
                f"no burn split closes the distance with a fixed {intent.fixed_coast_s:.0f}s coast at "
                "this acceleration; using the minimum-time profile instead"
            )
            mode = "minimum_time"
    elif intent.desired_eta_s is not None:
        mode = "desired_eta"
        eta = intent.desired_eta_s
        if eta > t_min_total * (1 + 1e-6):
            three = _three_phase(accel_used, v0, vf, d, eta)
            if three is not None:
                t1, t_coast, t2 = three
                total_time = eta
            else:
                warnings.append(
                    f"desired ETA of {eta:.0f}s could not be matched with a coast phase at this "
                    "acceleration; using the minimum-time profile instead"
                )
                mode = "minimum_time"
        elif eta < t_min_total * (1 - 1e-6):
            warnings.append(
                f"desired ETA of {eta:.0f}s is shorter than the {t_min_total:.0f}s minimum-time burn "
                "at this acceleration; using the minimum-time profile instead"
            )
            mode = "minimum_time"

    # --- Speed cap: always hard. Auto-resolved only for minimum_time. -----
    speed_capped = False
    speed_cap_violated = False
    turnover_speed = v0 + accel_used * t1
    if intent.max_speed_ms is not None and turnover_speed > intent.max_speed_ms + 1e-6:
        if mode == "minimum_time":
            capped = _speed_capped_two_phase(accel_used, v0, vf, d, intent.max_speed_ms)
            if capped is not None:
                t1, t_coast, t2 = capped
                total_time = t1 + t_coast + t2
                turnover_speed = intent.max_speed_ms
                speed_capped = True
            else:
                speed_cap_violated = True
                warnings.append(
                    f"current or arrival closing speed already exceeds the {intent.max_speed_ms:.0f} m/s "
                    "cap — a decelerate-first profile would be needed and isn't modeled"
                )
        else:
            speed_cap_violated = True
            warnings.append(
                f"the {mode.replace('_', ' ')} schedule needs a peak closing speed of "
                f"{turnover_speed:.0f} m/s, above the {intent.max_speed_ms:.0f} m/s cap — relax the "
                "schedule or raise the speed cap"
            )

    dv_longitudinal = accel_used * (t1 + t2)
    dv_cross = abs(target.cross_speed_ms) if intent.null_cross_track else 0.0
    dv_total = dv_longitudinal + dv_cross

    dv_available = ship.available_delta_v_ms()
    dv_budget = dv_margin = None
    feasible = not speed_cap_violated
    if dv_available is not None:
        dv_budget = dv_available * (1 - intent.dv_margin_frac)
        dv_margin = dv_budget - dv_total
        if dv_total > dv_budget:
            feasible = False
            warnings.append(
                f"burn needs {dv_total:.0f} m/s but only {dv_budget:.0f} m/s is budgeted after the "
                f"{intent.dv_margin_frac:.0%} margin (of {dv_available:.0f} m/s available)"
            )
    else:
        warnings.append("ship delta-v budget unknown — feasibility not checked")

    if accel_used >= accel_max - 1e-9:
        warnings.append("burning at the ship's raw thrust ceiling with no margin")

    phases = [BurnPhase("burn_prograde", t1, accel_used * t1)]
    if t_coast > 1e-6:
        phases.append(BurnPhase("coast", t_coast, 0.0))
    phases.append(BurnPhase("burn_retro", t2, accel_used * t2))

    return BurnPlan(
        feasible=feasible,
        warnings=warnings,
        mode=mode,
        speed_capped=speed_capped,
        accel_used_ms2=accel_used,
        accel_used_g=accel_used / G0,
        phases=phases,
        total_time_s=total_time,
        turnover_speed_ms=turnover_speed,
        dv_longitudinal_ms=dv_longitudinal,
        dv_cross_ms=dv_cross,
        dv_total_ms=dv_total,
        dv_available_ms=dv_available,
        dv_budget_ms=dv_budget,
        dv_margin_ms=dv_margin,
    )
