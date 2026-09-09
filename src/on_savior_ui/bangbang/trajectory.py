"""2D trajectory reconstruction and closest-approach analysis for a BurnPlan.

Local-flat approximation, built on the same numbers already in a
:class:`~on_savior_ui.bangbang.model.BurnPlan`: along-track motion follows
the burn's own bang-bang kinematics (accelerate / optional coast /
decelerate, straight along the original line of sight); cross-track motion
is the target's cross velocity carried forward unopposed, unless
``Intent.null_cross_track`` cancels it. Cancellation is billed in
:mod:`.model` as a lump-sum delta-v, not simulated as a continuous
correction burn, so the cross-track path here is either "drifting at a
constant rate" or "held flat at zero" — never a smooth transition between
the two. This is a good picture as long as cross-track drift stays small
next to the range (the normal case this tool targets); it is not a full
pursuit / proportional-navigation solve, and doesn't need to be to answer
"how close, and to which side."

Points are sampled evenly in *time*, not distance or arc length, on
purpose: the burn's acceleration phases (fast burn, slow burn, coast) are
exactly what should read as bunched-together vs. spread-out points along
the path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .model import BurnPlan, Intent, TargetData


@dataclass
class TrajectoryPoint:
    t_s: float
    along_track_m: float  # distance remaining to the target's along-track position
    cross_track_m: float  # signed lateral offset from the original line of sight
    range_m: float  # true distance to target = hypot(along_track_m, cross_track_m)


@dataclass
class ClosestApproach:
    t_s: float
    along_track_m: float
    cross_track_m: float
    range_m: float
    bearing_deg: float  # 0 = dead ahead, +90 = right, -90 = left, ±180 = behind
    side: str  # "left" | "right" | "dead ahead"


@dataclass
class _Segment:
    t_start: float
    t_end: float
    x_start: float
    v_start: float
    accel: float

    def position(self, t: float) -> tuple[float, float]:
        tau = min(max(t, self.t_start), self.t_end) - self.t_start
        x = self.x_start - (self.v_start * tau + 0.5 * self.accel * tau * tau)
        v = self.v_start + self.accel * tau
        return x, v


def _segments(plan: BurnPlan, distance_m: float) -> list[_Segment]:
    a = plan.accel_used_ms2
    v = plan.turnover_speed_ms - a * plan.phases[0].duration_s
    x = distance_m
    t = 0.0
    segments: list[_Segment] = []
    for phase in plan.phases:
        accel = a if phase.kind == "burn_prograde" else (-a if phase.kind == "burn_retro" else 0.0)
        seg = _Segment(t_start=t, t_end=t + phase.duration_s, x_start=x, v_start=v, accel=accel)
        segments.append(seg)
        x, v = seg.position(seg.t_end)
        t = seg.t_end
    return segments


def _along_track_at(segments: list[_Segment], t: float) -> float:
    for seg in segments:
        if t <= seg.t_end + 1e-9:
            return seg.position(t)[0]
    return segments[-1].position(segments[-1].t_end)[0]


def _cross_track_at(target: TargetData, intent: Intent, t: float) -> float:
    if intent.null_cross_track:
        return 0.0
    return target.cross_speed_ms * t


def build_trajectory(
    plan: BurnPlan, target: TargetData, intent: Intent, n_points: int = 24
) -> tuple[list[TrajectoryPoint], ClosestApproach] | None:
    """Evenly-time-spaced trajectory points, plus the closest-approach point.

    Returns None if the plan has no burn to trace (infeasible with no
    solution — see BurnPlan.phases).
    """
    if not plan.phases or plan.total_time_s <= 0:
        return None

    segments = _segments(plan, target.distance_m)

    n = max(2, n_points)
    points = []
    for i in range(n):
        t = i * plan.total_time_s / (n - 1)
        x = _along_track_at(segments, t)
        y = _cross_track_at(target, intent, t)
        points.append(TrajectoryPoint(t_s=t, along_track_m=x, cross_track_m=y, range_m=math.hypot(x, y)))

    # Dense grid search for closest approach — the path is only piecewise
    # smooth, and a closed-form minimum isn't worth it for a visualizer.
    fine_n = 2000
    best: tuple[float, float, float, float] | None = None
    for i in range(fine_n + 1):
        t = i * plan.total_time_s / fine_n
        x = _along_track_at(segments, t)
        y = _cross_track_at(target, intent, t)
        r = math.hypot(x, y)
        if best is None or r < best[3]:
            best = (t, x, y, r)
    t_ca, x_ca, y_ca, r_ca = best
    bearing = math.degrees(math.atan2(y_ca, x_ca))
    side = "dead ahead" if abs(y_ca) < 1e-6 else ("right" if y_ca > 0 else "left")

    closest = ClosestApproach(
        t_s=t_ca, along_track_m=x_ca, cross_track_m=y_ca, range_m=r_ca, bearing_deg=bearing, side=side
    )
    return points, closest
