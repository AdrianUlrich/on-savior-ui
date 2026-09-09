"""Streamlit front-end for the bang-bang burn planner.

Pure UI: all physics lives in :mod:`on_savior_ui.bangbang.model`. Run with

    uv run on-savior-ui bangbang

or directly via ``uv run streamlit run src/on_savior_ui/bangbang/app.py``.
"""

from __future__ import annotations

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from on_savior_ui.bangbang.economics import EconomicsRates, estimate_cost
from on_savior_ui.bangbang.model import Intent, ShipData, TargetData, plan_burn
from on_savior_ui.bangbang.trajectory import build_trajectory

st.set_page_config(page_title="Bang-Bang Burn Planner", page_icon="🚀", layout="wide")

st.title("🚀 Bang-bang burn planner")
st.caption(
    "Accelerate, flip, decelerate — optionally with a coast in between — to close on a "
    "target. **Data** below is what a flight-management computer could plausibly show you "
    "(entered by hand today; a save-file loader will fill it in later — see "
    "`on_savior_ui.bangbang.save_bridge`). **Intent** is your burn profile, which is never "
    "loadable from a save."
)

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
st.header("Data — ship and target readout")
ship_col, target_col = st.columns(2)

with ship_col:
    st.subheader("Ship capability")
    ship_name = st.text_input("Ship", value="", placeholder="unnamed")
    wet_mass_t = st.number_input("Wet mass (t)", min_value=0.0, value=45.0, step=1.0)
    max_thrust_kn = st.number_input("Max thrust (kN)", min_value=0.0, value=180.0, step=10.0)
    dv_mode = st.radio(
        "Delta-v budget", ["enter directly", "derive from Isp + dry mass"], horizontal=True
    )
    dry_mass_t: float | None = None
    isp_s: float | None = None
    dv_available: float | None = None
    if dv_mode == "enter directly":
        dv_available = st.number_input("Delta-v available (m/s)", min_value=0.0, value=2500.0, step=50.0)
    else:
        dry_mass_t = st.number_input("Dry mass (t)", min_value=0.0, value=30.0, step=1.0)
        isp_s = st.number_input("Isp (s)", min_value=0.0, value=320.0, step=10.0)

with target_col:
    st.subheader("Target track")
    target_name = st.text_input("Target", value="", placeholder="unidentified contact")
    distance_km = st.number_input("Range (km)", min_value=0.0, value=120.0, step=5.0)
    closing_speed = st.number_input(
        "Closing speed (m/s)",
        value=-40.0,
        step=5.0,
        help="Positive = the gap is closing on its own; negative = opening (target receding).",
    )
    cross_speed = st.number_input(
        "Cross/lateral speed (m/s)",
        value=8.0,
        step=1.0,
        help=(
            "Relative velocity component perpendicular to the line of sight. Signed: positive = "
            "target drifting right of your heading, negative = left. Left unopposed by default "
            "(see Null cross-track velocity, in the sidebar) — see the Trajectory section below "
            "for where it lands you."
        ),
    )
    has_eta = st.checkbox("Onboard inertial ETA readout available", value=True)
    eta_min = st.number_input(
        "Inertial ETA (minutes)", min_value=0.0, value=25.0, step=1.0, disabled=not has_eta,
        help=(
            "The flight computer's own projection: time to zero range if the current closing "
            "speed simply persists, with no burn. Informational only — it is not fed into the "
            "burn plan below. A *desired* arrival time is set under Intent, in the sidebar."
        ),
    )

st.caption(
    "Placeholder numbers above — swap in your own readout. Range, closing speed, cross "
    "speed, and inertial ETA are each independently derived onboard and can disagree; this "
    "tool doesn't reconcile them yet (see docs/bangbang.md)."
)

# ---------------------------------------------------------------------------
# Intent
# ---------------------------------------------------------------------------
st.sidebar.header("Intent — burn profile")
preset = st.sidebar.selectbox("Preset", ["standard", "conservative", "aggressive", "custom"], index=0)
base = Intent.preset(preset) if preset != "custom" else Intent()

st.sidebar.subheader("Schedule")
st.sidebar.caption(
    "Fixed coast beats desired arrival beats fastest — see docs/bangbang.md for the "
    "precedence rules when more than one is set."
)
want_desired_eta = st.sidebar.checkbox("Desired arrival time", value=False)
desired_eta_min = st.sidebar.number_input(
    "Desired arrival (minutes)", min_value=0.0, value=40.0, step=1.0, disabled=not want_desired_eta,
    help="Soft target — met if reachable, else relaxed to the fastest profile with a warning.",
)
want_fixed_coast = st.sidebar.checkbox("Fixed coast duration", value=False)
fixed_coast_h = st.sidebar.number_input(
    "Fixed coast (hours)", min_value=0.0, value=6.0, step=0.5, disabled=not want_fixed_coast,
    help="Hard commitment — e.g. to fit a sleep shift. Overrides a desired arrival time if both are set.",
)
want_max_speed = st.sidebar.checkbox("Speed cap", value=False)
max_speed = st.sidebar.number_input(
    "Max closing speed (m/s)", min_value=0.0, value=100.0, step=5.0, disabled=not want_max_speed,
    help="A local speed limit or other precaution. Always enforced — auto-applied against the "
         "fastest profile, but reported infeasible if it conflicts with an explicit schedule above.",
)

st.sidebar.subheader("Burn shape")
arrival_speed = st.sidebar.number_input(
    "Arrival closing speed (m/s)",
    value=base.arrival_speed_ms,
    step=1.0,
    help="0 = matched velocity (dock/rendezvous); positive = flyby speed.",
)
null_cross = st.sidebar.checkbox(
    "Null cross-track velocity",
    value=base.null_cross_track,
    help=(
        "Off by default: an unopposed cross-track drift is left in the plan, so the Trajectory "
        "section below can show how close the approach actually comes and to which side. Turn on "
        "to price in a delta-v cost for cancelling it and fly straight down the line of sight."
    ),
)
preferred_g = st.sidebar.slider(
    "Preferred acceleration cap (G)", 0.05, 2.0, value=base.preferred_accel_g or 1.0, step=0.05
)
thrust_margin = st.sidebar.slider(
    "Thrust margin", 0.0, 0.5, value=base.thrust_margin_frac, step=0.05,
    help="Fraction of max thrust held in reserve.",
)
dv_margin = st.sidebar.slider(
    "Delta-v margin", 0.0, 0.5, value=base.dv_margin_frac, step=0.05,
    help="Fraction of the delta-v budget held in reserve (return trip, correction burns…).",
)

intent = Intent(
    arrival_speed_ms=arrival_speed,
    null_cross_track=null_cross,
    preferred_accel_g=preferred_g,
    thrust_margin_frac=thrust_margin,
    dv_margin_frac=dv_margin,
    desired_eta_s=(desired_eta_min * 60) if want_desired_eta else None,
    fixed_coast_s=(fixed_coast_h * 3600) if want_fixed_coast else None,
    max_speed_ms=max_speed if want_max_speed else None,
)

ship = ShipData(
    name=ship_name,
    wet_mass_kg=wet_mass_t * 1000,
    max_thrust_N=max_thrust_kn * 1000,
    delta_v_available_ms=dv_available,
    dry_mass_kg=(dry_mass_t * 1000) if dry_mass_t is not None else None,
    isp_s=isp_s,
)
target = TargetData(
    name=target_name,
    distance_m=distance_km * 1000,
    closing_speed_ms=closing_speed,
    cross_speed_ms=cross_speed,
    eta_s=(eta_min * 60) if has_eta else None,
)

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
st.header("Burn plan")
try:
    plan = plan_burn(ship, target, intent)
except ValueError as exc:
    st.error(str(exc))
    st.stop()

mode_label = {
    "minimum_time": "fastest (minimum time)",
    "desired_eta": "desired arrival time",
    "fixed_coast": "fixed coast duration",
}[plan.mode]
cap_note = " · speed-capped" if plan.speed_capped else ""
status = st.success if plan.feasible else st.error
status(f"{'Feasible' if plan.feasible else 'Not feasible'} — schedule: {mode_label}{cap_note}")
for warning in plan.warnings:
    st.warning(warning)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total time", f"{plan.total_time_s / 60:.1f} min")
m2.metric("Accel used", f"{plan.accel_used_g:.2f} G")
m3.metric("Turnover speed", f"{plan.turnover_speed_ms:.0f} m/s")
m4.metric("Delta-v needed", f"{plan.dv_total_ms:.0f} m/s")

if plan.dv_available_ms is not None and plan.dv_budget_ms is not None:
    st.progress(
        min(1.0, plan.dv_total_ms / max(plan.dv_available_ms, 1e-9)),
        text=(
            f"{plan.dv_total_ms:.0f} / {plan.dv_available_ms:.0f} m/s available "
            f"({plan.dv_budget_ms:.0f} m/s after margin)"
        ),
    )

if plan.phases:
    phase_df = pd.DataFrame(
        [
            {
                "phase": p.kind,
                "duration (min)": p.duration_s / 60,
                "delta-v (m/s)": p.delta_v_ms,
            }
            for p in plan.phases
        ]
    )
    st.dataframe(phase_df, hide_index=True, width="stretch")

    t1 = plan.phases[0].duration_s
    t_coast = plan.phases[1].duration_s if len(plan.phases) == 3 else 0.0
    t_sample = np.linspace(0, plan.total_time_s, 200)
    speed = np.where(
        t_sample <= t1,
        target.closing_speed_ms + plan.accel_used_ms2 * t_sample,
        np.where(
            t_sample <= t1 + t_coast,
            target.closing_speed_ms + plan.accel_used_ms2 * t1,
            plan.turnover_speed_ms - plan.accel_used_ms2 * (t_sample - t1 - t_coast),
        ),
    )
    chart_df = pd.DataFrame({"t (min)": t_sample / 60, "closing speed (m/s)": speed}).set_index("t (min)")
    st.line_chart(chart_df)

# ---------------------------------------------------------------------------
# Trajectory
# ---------------------------------------------------------------------------
st.header("Trajectory")
st.caption(
    "Ship position relative to the target (fixed at the cross). Points are evenly spaced in "
    "**time**, not distance, so the burn's acceleration phases show up directly as bunched-together "
    "(slow) vs. spread-out (fast) points along the path."
)
n_points = st.slider("Sample points", min_value=8, max_value=80, value=24, step=1)

trajectory = build_trajectory(plan, target, intent, n_points=n_points)
if trajectory is None:
    st.info("No trajectory to show for this plan.")
else:
    points, closest = trajectory
    traj_df = pd.DataFrame(
        [
            {
                "along_track_m": p.along_track_m,
                "cross_track_m": p.cross_track_m,
                "t_min": p.t_s / 60,
                "range_m": p.range_m,
            }
            for p in points
        ]
    )
    tooltip = [
        alt.Tooltip("t_min", title="t (min)", format=".1f"),
        alt.Tooltip("along_track_m", title="along-track (m)", format=".0f"),
        alt.Tooltip("cross_track_m", title="cross-track (m)", format=".0f"),
        alt.Tooltip("range_m", title="range (m)", format=".0f"),
    ]
    x_enc = alt.X("along_track_m", title="Along-track distance to target (m)", scale=alt.Scale(reverse=True))
    y_enc = alt.Y("cross_track_m", title="Cross-track offset (m) — positive = right")

    line = alt.Chart(traj_df).mark_line(color="#3b82f6").encode(x=x_enc, y=y_enc)
    dots = alt.Chart(traj_df).mark_circle(size=70, color="#3b82f6").encode(x=x_enc, y=y_enc, tooltip=tooltip)
    target_mark = (
        alt.Chart(pd.DataFrame([{"along_track_m": 0.0, "cross_track_m": 0.0}]))
        .mark_point(shape="cross", size=260, color="#ef4444", strokeWidth=3)
        .encode(x=x_enc, y=y_enc)
    )
    closest_mark = (
        alt.Chart(pd.DataFrame([{"along_track_m": closest.along_track_m, "cross_track_m": closest.cross_track_m}]))
        .mark_point(shape="diamond", size=180, color="#f59e0b", filled=True)
        .encode(x=x_enc, y=y_enc)
    )
    chart = (line + dots + target_mark + closest_mark).properties(height=420).interactive()
    st.altair_chart(chart, width="stretch")

    c1, c2, c3 = st.columns(3)
    c1.metric("Closest approach", f"{closest.range_m:,.0f} m")
    c2.metric("Bearing", f"{closest.bearing_deg:+.0f}° ({closest.side})")
    c3.metric("Time of closest approach", f"{closest.t_s / 60:.1f} min")
    st.caption(
        "Bearing: 0° = dead ahead along the original line of sight, +90° = directly to your right, "
        "−90° = directly to your left, ±180° = behind. Cross-track marker on the chart (◆) marks "
        "closest approach; the target sits at the cross (✚)."
    )

# ---------------------------------------------------------------------------
# Economics
# ---------------------------------------------------------------------------
st.header("Economics")
rate_col, breakdown_col = st.columns([1, 1.3])

with rate_col:
    st.subheader("Rates")
    license_per_day = st.number_input("License cost ($/day)", min_value=0.0, value=5000.0, step=100.0)
    fuel_per_kg = st.number_input("Fuel cost ($/kg propellant)", min_value=0.0, value=20.0, step=1.0)
    crew_count = st.number_input("Crew count", min_value=0, value=1, step=1)
    o2_per_kg = st.number_input("Life support O2 cost ($/kg)", min_value=0.0, value=5.0, step=0.5)
    o2_per_crew_day = st.number_input(
        "O2 consumption (kg/crew/day)", min_value=0.0, value=0.84, step=0.01,
        help="Typical adult metabolic O2 use is ~0.84 kg/day; adjust to match the game's life-support rate.",
    )
    if isp_s is not None:
        cost_isp_s = isp_s
        st.caption(f"Fuel-mass conversion uses the ship's Isp above: {isp_s:.0f} s")
    else:
        cost_isp_s = st.number_input(
            "Isp for fuel-mass conversion (s)", min_value=0.0, value=320.0, step=10.0,
            help="Needed to convert this burn's delta-v into a propellant mass to price.",
        )

rates = EconomicsRates(
    license_cost_per_day=license_per_day,
    fuel_cost_per_kg=fuel_per_kg,
    crew_count=int(crew_count),
    o2_cost_per_kg=o2_per_kg,
    o2_kg_per_crew_per_day=o2_per_crew_day,
    isp_s=cost_isp_s,
)
cost = estimate_cost(plan, ship, rates)

with breakdown_col:
    st.subheader("Breakdown")
    for warning in cost.warnings:
        st.warning(warning)

    rows = [
        {"item": "License", "amount ($)": cost.license_cost},
        {"item": "Life support", "amount ($)": cost.life_support_cost},
    ]
    if cost.fuel_cost is not None:
        rows.append({"item": "Fuel", "amount ($)": cost.fuel_cost})
    rows.append({"item": "Total", "amount ($)": cost.total_cost})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    st.metric("Total estimated cost", f"${cost.total_cost:,.0f}")
    duration_label = (
        f"{cost.duration_days:.2f} days" if cost.duration_days >= 1
        else f"{cost.duration_days * 24:.2f} hours"
    )
    if cost.propellant_mass_kg is not None:
        st.caption(f"{cost.propellant_mass_kg:,.0f} kg propellant over {duration_label} ({rates.crew_count} crew)")
    else:
        st.caption(f"{duration_label} ({rates.crew_count} crew)")
