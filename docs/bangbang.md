# Bang-bang burn planner

A Streamlit app for planning a Newtonian intercept/rendezvous burn: burn
toward the target, flip, burn to kill the closing rate — with an optional
coast phase in the middle if you have time to spare.

```console
$ uv run on-savior-ui bangbang
```

Opens at `http://localhost:8501`. `--port` and `--host` behave like `serve`
(`--host 0.0.0.0` to reach it from another device).

## Data vs. intent

The planner is split into two dataclasses, matching what the game's own
instruments could and couldn't tell you:

- **`ShipData`** / **`TargetData`** (`on_savior_ui.bangbang.model`) — the
  ship's wet mass, max thrust, and delta-v budget; the target's range,
  closing rate, cross-track rate, and the flight computer's own **inertial**
  ETA readout. Entered by hand in the UI today. `on_savior_ui.bangbang.save_bridge`
  holds the (currently stubbed) functions that will fill these in from a
  save once one is available to inspect — see its docstring for what's
  still unverified.

  This keeps faith with the project's no-cheating principle: only values a
  flight-management computer could plausibly show, never a target's true
  state. Range, closing speed, cross speed, and ETA are each independently
  derived onboard and can disagree — the planner doesn't reconcile them
  (imprecision modeling is TBD; `TargetData` has unused
  `distance_uncertainty_frac` / `speed_uncertainty_ms` fields reserved for it).

  `TargetData.eta_s` is *not* a plan input — it's what the instruments say
  would happen with no burn at all (distance / current closing speed,
  extrapolated). `plan_burn` never reads it; it exists purely for the pilot
  to eyeball against the other readouts. A *desired* arrival time is intent,
  below.

- **`Intent`** — the desired burn profile. `arrival_speed_ms` (closing speed
  at zero range; 0 = matched velocity/dock), `null_cross_track` (**off** by
  default — see [Trajectory](#trajectory--closest-approach) below for why),
  `preferred_accel_g`, and margins on thrust and delta-v behave as before.
  Three more fields shape the *schedule*, and compete when more than one is
  set:

  | Field | Meaning | Precedence |
  |---|---|---|
  | `fixed_coast_s` | Hard commitment to coast this long (e.g. a sleep shift) | Wins outright |
  | `desired_eta_s` | Soft target arrival time | Used only if no fixed coast is set |
  | *(neither)* | Minimum time — burn hardest allowed, no coast | Default |
  | `max_speed_ms` | Local speed limit / precaution — always enforced | Applied on top of whichever of the above wins |

  None of this comes from a save; it's pilot preference.
  `Intent.preset("standard" | "conservative" | "aggressive")` gives sane
  defaults for the non-schedule fields; `"conservative"` runs a lower G-cap
  and bigger margins, `"aggressive"` the opposite. The schedule fields
  default to unset (minimum time) in every preset — they're situational, not
  a general aggressiveness dial.

`plan_burn(ship, target, intent)` returns a `BurnPlan`: which `mode` was
used (`minimum_time` / `desired_eta` / `fixed_coast`), whether the speed cap
ended up binding (`speed_capped`), the phase list (`burn_prograde`, optional
`coast`, `burn_retro`) with durations and delta-v, total time, turnover
speed, delta-v needed vs. budgeted after margin, a `feasible` flag, and
human-readable `warnings`.

## Physics

Both phases burn at the same acceleration magnitude, direction reversed at
the turnover — the classic "flip and burn." Given initial closing speed
`v0`, desired arrival closing speed `vf`, distance `d`, and acceleration `a`:

- **Minimum time (default):** solve `a*t1^2 + 2*v0*t1 + (v0*k − a*k²/2 − d) = 0`
  where `k = (v0 − vf) / a`, `t2 = t1 + k`. This is the shortest possible
  time at that acceleration; delta-v spent is `a*(t1+t2)`.
- **Desired arrival time:** if `desired_eta_s` is longer than the minimum
  time, solve instead for the burn split that spends exactly that much
  time: `a*t1^2 − a*(T−k)*t1 + (d − v0*T + a*k²/2) = 0`. A longer target
  means a shorter, cheaper burn — coasting trades time for delta-v. If it's
  shorter than the minimum time, it's unreachable at this acceleration; fall
  back to minimum time with a warning.
- **Fixed coast:** if `fixed_coast_s` is set, the coast duration is no
  longer free — it's fixed, and the total time falls out instead:
  `a*t1^2 + (2*v0 + a*C)*t1 + (v0*C + v0*k − a*k²/2 − d) = 0` where
  `C = fixed_coast_s` (reduces to the minimum-time equation at `C=0`).
  Wins over `desired_eta_s` if both are set — the resulting arrival time and
  its delta from the desired one are reported as a warning rather than
  silently dropped.
- **Speed cap:** if the schedule above would exceed `max_speed_ms`, and no
  more specific schedule was requested (mode is minimum-time), burn to the
  cap, coast at the cap for whatever distance is left, then decelerate —
  the fastest way to cover the distance without exceeding it. Against an
  explicit `desired_eta_s` or `fixed_coast_s`, a cap violation is reported
  as infeasible rather than solved for automatically: satisfying both an
  exact schedule and a speed cap in general needs a different burn shape
  than either alone, and guessing at one would be worse than saying so.
- **Cross-track:** nulling the lateral velocity component is added to the
  longitudinal delta-v directly (not RSS-combined) — a conservative
  overestimate rather than an optimistic one.
- **Acceleration used** is `min(max_thrust / wet_mass, preferred_G) * (1 − thrust_margin)`
  — wet (not dry) mass, so it's the *worst-case* (lowest) acceleration
  available over the whole burn, again erring conservative.

Scope: this only models the single-switch accelerate-then-decelerate
profile, which covers the normal approach case. If no such solution exists
(e.g. the target is receding faster than the burn can catch, or the
geometry would need braking before accelerating), `plan_burn` reports
infeasible with a warning rather than guessing at a different control
policy.

## Trajectory & closest approach

Below the burn-plan chart, `on_savior_ui.bangbang.trajectory.build_trajectory`
reconstructs the ship's 2D position relative to the target — along-track
distance from the burn's own kinematics, cross-track offset from
`TargetData.cross_speed_ms` carried forward unopposed (or held at zero if
`Intent.null_cross_track` is on) — and searches it for the closest-approach
point: range, time, and bearing (0° = dead ahead, +90°/−90° = right/left).

`null_cross_track` defaults to **off**, unlike the rest of `Intent`'s
defaults, which lean conservative: with it on there's nothing to show here —
the trajectory is a straight line and every approach is a perfect intercept
by construction. Off is what makes the visualizer meaningful; turning it on
still works (it prices in the cancellation delta-v and flies straight), it
just isn't the interesting case for this section.

Points on the chart are sampled **evenly in time**, not in distance — that's
deliberate. A bang-bang burn's speed varies a lot (slow near the turnover
and at either end if arrival speed is 0, fast in between), and time-even
sampling turns that directly into visible spacing along the path: bunched
points where the ship is slow, spread-out points where it's fast. The
closest-approach point itself is found on a much finer internal time grid
(not the displayed points) since the path is only piecewise-smooth and
picking a global minimum in closed form isn't worth it here.

This shares the local-flat approximation already used for the burn itself:
along-track motion in a straight line, cross-track drift in a straight line,
independent of each other. It doesn't model how the line-of-sight bearing
itself rotates as you approach with an offset (a full pursuit /
proportional-navigation problem) — good enough while the drift stays small
relative to the range, which is the regime this tool targets, but it will
understate curvature on a large, slow drift over a long approach.

## Economics

Below the plan, a small subcalculator prices it: `on_savior_ui.bangbang.economics`
takes the `BurnPlan` plus an `EconomicsRates` (license $/day, fuel $/kg
propellant, crew count, O2 $/kg, O2 kg/crew/day, and an Isp for converting
delta-v to propellant mass) and returns a `CostBreakdown` — license, life
support, and fuel cost, plus the total.

Like `Intent`, none of this is sensor data or burn intent — it's business
input, entered right next to the breakdown it produces (rather than folded
into `Intent`, since a rate like "fuel $/kg" describes the market, not the
maneuver). Fuel cost needs an Isp to turn this burn's delta-v into a
propellant mass via Tsiolkovsky (`wet_mass * (1 - exp(-dv / (Isp·g0)))`); if
the ship didn't supply one (because its delta-v budget was entered directly),
the rates carry their own `isp_s` so costing still works, and the breakdown
warns rather than silently omitting fuel cost.

## Extending

`on_savior_ui.bangbang.model` has no Streamlit import — it's plain
dataclasses and functions, usable from the CLI, tests, or another UI.
`on_savior_ui.bangbang.app` is UI only. To wire in real save data, implement
`ship_data_from_save` / `target_data_from_save` in `save_bridge.py` once a
save is available to find the actual field names, then call them from
`app.py` behind a "load from save" button.
