import numpy as np
from scipy.integrate import solve_ivp
from environment import get_gravity, get_air_density
from constants import Re, v_rot, omega

def equations_of_motion(t, state, rocket):
    x, y, vx, vy = state

    r        = np.sqrt(x**2 + y**2)
    altitude = r - Re
    mass     = rocket.get_mass(t)

    r_hat = np.array([x, y]) / r
    t_hat = np.array([-y, x]) / r

    # --- 1. Gravity ---
    g     = get_gravity(altitude)
    g_vec = -g * r_hat

    # --- 2. Thrust ---
    thrust     = rocket.get_thrust(t, altitude)
    angle      = rocket.get_pitch_angle(t)
    thrust_vec = (thrust / mass) * (np.cos(angle) * r_hat + np.sin(angle) * t_hat)

    # --- 3. Drag (relative to atmosphere, which co-rotates with Earth) ---
    v_atm        = omega * r * t_hat          # Atmospheric velocity at current position
    v_vec        = np.array([vx, vy])
    v_rel        = v_vec - v_atm              # Velocity relative to air
    v_rel_mag    = np.linalg.norm(v_rel)

    rho  = get_air_density(max(altitude, 0))
    drag = 0.5 * rho * v_rel_mag**2 * rocket.Cd * rocket.A

    drag_vec = (-drag / mass) * (v_rel / v_rel_mag) if v_rel_mag > 0 else np.zeros(2)

    # --- Total acceleration ---
    a = g_vec + thrust_vec + drag_vec

    return [vx, vy, a[0], a[1]]


def _build_stage_events(rocket):
    """
    Generates a scipy event function for each staging event.
    Each event triggers at the cutoff time of its stage,
    causing solve_ivp to restart with updated rocket mass.
    """
    events = []
    for _, _, t_cutoff in rocket.timeline[:-1]:   # No event needed for last stage
        def make_event(tc):
            def event(t, state, rocket):
                return t - tc
            event.terminal  = True                # Stop integration at this point
            event.direction = 1                   # Trigger when crossing upward
            return event
        events.append(make_event(t_cutoff))
    return events


def run_simulation(rocket, t_end=None, dt=0.5):
    """
    Integrates the equations of motion across all staging events, AND
    (when the rocket's guidance supports it, i.e. PEGGuidance) periodically
    re-solves the steering law from the real, current state — closed-loop
    replanning — and checks whether the target orbit has actually been
    reached, cutting off the engines right there even if propellant is
    still left in the current stage.

    Returns:
        t_all : np.array - Time array across the full flight
        y_all : np.array - State array [x, y, vx, vy] across the full flight
    """
    state0 = [Re, 0.0, 0.0, v_rot]   # Launched from equator, at rest
    t_all  = []
    y_all  = []

    guidance   = rocket.guidance
    replan_dt  = getattr(guidance, "REPLAN_INTERVAL", None)
    has_cutoff = hasattr(guidance, "should_cutoff")

    # Nominal (full-propellant) stage cutoffs, plus an outer safety bound —
    # actual engine cutoff may happen earlier if should_cutoff() fires.
    breakpoints = [t_cut for _, _, t_cut in rocket.timeline[:-1]]
    if t_end is None:
        t_end = rocket.timeline[-1][2] * 1.2
    stage_breaks = [0.0] + breakpoints + [t_end]

    state          = state0
    cutoff_reached = False

    for seg_start, seg_stop in zip(stage_breaks[:-1], stage_breaks[1:]):
        if cutoff_reached:
            break

        sub_t = seg_start
        while sub_t < seg_stop - 1e-9:
            sub_stop = min(sub_t + replan_dt, seg_stop) if replan_dt else seg_stop

            if hasattr(guidance, "replan"):
                guidance.replan(sub_t, state, rocket)

            solution = solve_ivp(
                fun      = lambda t, s: equations_of_motion(t, s, rocket),
                t_span   = (sub_t, sub_stop),
                y0       = state,
                method   = 'RK45',
                max_step = dt,
                dense_output = True
            )

            t_all.append(solution.t)
            y_all.append(solution.y)
            state = solution.y[:, -1]
            sub_t = sub_stop

            if has_cutoff and guidance.should_cutoff(sub_t, state, rocket):
                cutoff_reached = True
                break

    return np.concatenate(t_all), np.hstack(y_all)


def get_telemetry(t_all, y_all, rocket):
    x, y, vx, vy = y_all

    r        = np.sqrt(x**2 + y**2)
    altitude = r - Re
    speed    = np.sqrt(vx**2 + vy**2)
    rho      = np.array([get_air_density(max(a, 0)) for a in altitude])

    # Dynamic pressure uses velocity relative to atmosphere
    t_hat_x  = -y / r
    t_hat_y  =  x / r
    v_atm_x  = omega * r * t_hat_x
    v_atm_y  = omega * r * t_hat_y
    vrel_x   = vx - v_atm_x
    vrel_y   = vy - v_atm_y
    v_rel    = np.sqrt(vrel_x**2 + vrel_y**2)
    q        = 0.5 * rho * v_rel**2            # Correct dynamic pressure

    mass      = np.array([rocket.get_mass(t) for t in t_all])
    theta     = np.unwrap(np.arctan2(y, x))
    downrange = Re * (theta - theta[0])

    # Acceleration in g — computed from consecutive speed values
    dt   = np.diff(t_all)
    dv   = np.diff(speed)
    # Avoid division by zero, pad with 0 at start
    accel_ms2 = np.concatenate([[0], np.where(dt > 0, dv / dt, 0)])
    accel_g   = accel_ms2 / 9.80665       # Convert m/s² to g

    return {
        "time"      : t_all,
        "altitude"  : altitude,
        "speed"     : speed,
        "downrange" : downrange,
        "dyn_pres"  : q,
        "mass"      : mass,
        "accel_g"   : accel_g,             # g - Net acceleration
    }

def run_coast(state0, t_start, t_end, dt=10.0):
    """
    Propagates the rocket state under gravity only (no thrust, no drag).
    Used for orbital coast phases after MECO and after burns.

    Parameters:
        state0  : [x, y, vx, vy] - Initial state
        t_start : s - Start time
        t_end   : s - End time
        dt      : s - Max timestep

    Returns:
        t_arr, y_arr - Same format as run_simulation output
    """
    def gravity_only(t, state):
        x, y, vx, vy = state
        r     = np.sqrt(x**2 + y**2)
        g     = get_gravity(r - Re)
        r_hat = np.array([x, y]) / r
        g_vec = -g * r_hat
        return [vx, vy, g_vec[0], g_vec[1]]

    solution = solve_ivp(
        fun          = gravity_only,
        t_span       = (t_start, t_end),
        y0           = state0,
        method       = "RK45",
        max_step     = dt,
        dense_output = True
    )

    return solution.t, solution.y