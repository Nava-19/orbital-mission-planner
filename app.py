import numpy as np
from flask import Flask, render_template, request, jsonify

from constants   import Mu, Re
from vehicle     import Rocket, Stage, GuidanceProfile
from solver      import run_simulation, get_telemetry, run_coast
from orbital     import compute_orbital_elements, circularize, state_at_apoapsis, propagate_orbit, hohmann_transfer
from environment import v_circular

app = Flask(__name__)

ORBIT_PRESETS = {
    "iss"   : {"label": "ISS (400 km)",      "alt": 400e3},
    "sso"   : {"label": "SSO (600 km)",      "alt": 600e3},
    "meo"   : {"label": "MEO (20 000 km)",   "alt": 20000e3},
    "geo"   : {"label": "GEO (35 786 km)",   "alt": 35786e3},
    "custom": {"label": "Custom altitude",   "alt": None},
}

def _jsonify_arrays(obj):
    """Recursively convert numpy arrays and scalars to JSON-serializable types."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _jsonify_arrays(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonify_arrays(i) for i in obj]
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    return obj

def _sanitize(obj):
    """Replace NaN/Inf with 0 and convert numpy types so Flask can serialize."""
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        if obj != obj or obj == float("inf") or obj == float("-inf"):
            return 0.0
        return float(obj)
    if isinstance(obj, list):
        return [_sanitize(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    return obj


@app.route("/")
def index():
    return render_template("index.html", presets=ORBIT_PRESETS)


@app.route("/run", methods=["POST"])
def run():
    cfg = request.get_json()

    # ── Build vehicle ──
    stage_cfgs = cfg["stages"]  # ordered list, bottom to top — any number of stages
    if len(stage_cfgs) < 1:
        return jsonify({"error": "At least one stage is required"}), 400

    stages = [
        Stage(
            dry_mass  = float(s["dry_mass"]),
            prop_mass = float(s["prop_mass"]),
            thrust    = float(s["thrust"]),
            Isp       = float(s["isp"]),
            Cd        = float(s.get("cd", 0.3)),
            A         = float(s.get("area", 10.52)),
        )
        for s in stage_cfgs
    ]

    target_alt   = float(cfg["target_alt"])      # m
    n_orbits     = float(cfg.get("n_orbits", 1.5))

    guidance = GuidanceProfile(
        t_vertical      = float(cfg.get("t_vertical", 20)),
        target_altitude = target_alt,
    )
    rocket = Rocket(
        stages       = stages,
        payload_mass = float(cfg.get("payload_mass", 22800)),
        guidance     = guidance,
    )

    print(f"Target: {target_alt/1000:.0f} km | t_end: {rocket.timeline[-1][2]*1.2:.0f}s")

    # ════════════════════════════════════════════
    # PHASE 1 — Powered ascent
    # ════════════════════════════════════════════
    t_end        = rocket.timeline[-1][2] * 1.2
    t_asc, y_asc = run_simulation(rocket, t_end=t_end)

    x_f, y_f, vx_f, vy_f = (
        y_asc[0][-1], y_asc[1][-1],
        y_asc[2][-1], y_asc[3][-1]
    )
    el_meco = compute_orbital_elements(x_f, y_f, vx_f, vy_f)

    # ════════════════════════════════════════════
    # PHASE 2 — Coast from MECO to parking orbit apoapsis
    # ════════════════════════════════════════════
    circ       = circularize(x_f, y_f, vx_f, vy_f)
    t_meco     = t_asc[-1]
    t_apo      = t_meco + circ["t_coast"]
    t_to_apo, y_to_apo = run_coast(
        [x_f, y_f, vx_f, vy_f], t_meco, t_apo
    )

    # ════════════════════════════════════════════
    # PHASE 3 — Decide: direct insertion or Hohmann transfer
    # ════════════════════════════════════════════
    parking_alt   = circ["alt_circular"]         # m — achieved circular orbit
    needs_hohmann = target_alt > parking_alt * 2 and target_alt > 2000e3
    transfer      = hohmann_transfer(parking_alt, target_alt) if needs_hohmann else None
    tr            = transfer  # always defined — None if no Hohmann

    if needs_hohmann and transfer is not None:
        tr = transfer   # local alias — always a dict inside this block

        # 3a — Half a parking orbit before transfer burn
        T_park      = circ["elements_final"]["T"]
        t_park_end  = t_apo + 0.5 * T_park
        state_park  = state_at_apoapsis(circ)
        t_park, y_park = run_coast(state_park, t_apo, t_park_end)

        # 3b — Transfer ellipse coast from parking perigee to target apogee
        x_p  = y_park[0][-1];  y_p  = y_park[1][-1]
        vx_p = y_park[2][-1];  vy_p = y_park[3][-1]
        r_p  = np.sqrt(x_p**2 + y_p**2)
        tx   = -y_p / r_p;  ty = x_p / r_p
        vx_boost    = vx_p + tr["dv1"] * tx
        vy_boost    = vy_p + tr["dv1"] * ty
        t_trans_end = t_park_end + tr["T_transfer"]
        t_trans, y_trans = run_coast(
            [x_p, y_p, vx_boost, vy_boost], t_park_end, t_trans_end
        )

        # 3c — Circularize at target altitude and coast n_orbits
        x_ta  = y_trans[0][-1];  y_ta = y_trans[1][-1]
        r_ta  = np.sqrt(x_ta**2 + y_ta**2)
        v_tgt = np.sqrt(Mu / r_ta)
        tx2   = -y_ta / r_ta;  ty2 = x_ta / r_ta
        state_tgt = [x_ta, y_ta, v_tgt * tx2, v_tgt * ty2]
        T_tgt     = 2 * np.pi * np.sqrt(r_ta**3 / Mu)
        t_tgt_end = t_trans_end + n_orbits * T_tgt
        t_tgt, y_tgt = run_coast(state_tgt, t_trans_end, t_tgt_end)

        t_full = np.concatenate([t_asc, t_to_apo, t_park, t_trans, t_tgt])
        y_full = np.hstack([y_asc, y_to_apo, y_park, y_trans, y_tgt])
        t_coast_start = t_trans_end
        T_orbit       = T_tgt

        # Orbit traces
        x_ell,  y_ell  = propagate_orbit(el_meco, above_surface_only=True)
        x_park_orb, y_park_orb = propagate_orbit(circ["elements_final"])
        theta       = np.linspace(0, 2 * np.pi, 1000)
        r_tgt_circ  = Re + target_alt
        x_final_orb = r_tgt_circ * np.cos(theta)
        y_final_orb = r_tgt_circ * np.sin(theta)
        # omega_peri points toward burn position (x_p, y_p) = perigee of transfer ellipse
        omega_burn = np.arctan2(y_p, x_p)
        tr_el_rot  = {**tr["elements_transfer"], "omega_peri": omega_burn}
        x_tr, y_tr = propagate_orbit(tr_el_rot, above_surface_only=False)

    else:
        # Direct insertion — coast parking orbit for n_orbits
        state_circ  = state_at_apoapsis(circ)
        T_orbit     = circ["elements_final"]["T"]
        t_orb_end   = t_apo + n_orbits * T_orbit
        t_orbit, y_orbit = run_coast(state_circ, t_apo, t_orb_end)

        t_full = np.concatenate([t_asc, t_to_apo, t_orbit])
        y_full = np.hstack([y_asc, y_to_apo, y_orbit])
        t_coast_start = t_apo

        x_ell,  y_ell  = propagate_orbit(el_meco, above_surface_only=True)
        x_final_orb, y_final_orb = propagate_orbit(circ["elements_final"])
        x_park_orb = x_final_orb   # same orbit
        y_park_orb = y_final_orb
        x_tr = y_tr = []

    # ════════════════════════════════════════════
    # Telemetry for full mission
    # ════════════════════════════════════════════
    tel = get_telemetry(t_full, y_full, rocket)

    # ── Automatic frame count, based on total mission duration ──
    # Sampling evenly-spaced INDICES of t_full (the old approach) is wrong:
    # t_full is far denser during powered ascent (integrated with a small
    # fixed step) than during coast/orbit phases (integrated with a much
    # larger step), so an index-uniform pick starves the long coast/transfer
    # phases of points — which shows up as visible straight-line "jumps"
    # instead of a smooth curve along the orbit.
    #
    # Instead we resample uniformly in TIME (interpolating every channel),
    # and size the frame count from the mission's total duration so short
    # missions stay light and long ones (multi-orbit coasts, Hohmann
    # transfers) still render a smooth curve — capped for browser performance.
    T_total          = float(t_full[-1] - t_full[0])
    FRAME_INTERVAL_S = 4.0      # target ~1 frame every 4 s of simulated time
    MIN_FRAMES       = 400
    MAX_FRAMES       = 1200
    n_frames = int(np.clip(T_total / FRAME_INTERVAL_S, MIN_FRAMES, MAX_FRAMES))

    t_frames         = np.linspace(t_full[0], t_full[-1], n_frames)
    x_frames         = np.interp(t_frames, t_full, y_full[0])
    y_frames         = np.interp(t_frames, t_full, y_full[1])
    speed_frames     = np.interp(t_frames, t_full, tel["speed"])
    alt_frames       = np.interp(t_frames, t_full, tel["altitude"])
    mass_frames      = np.interp(t_frames, t_full, tel["mass"])
    downrange_frames = np.interp(t_frames, t_full, tel["downrange"])
    accel_frames     = np.interp(t_frames, t_full, tel["accel_g"])

    result = {
        "t"         : t_frames.tolist(),
        "x"         : x_frames.tolist(),
        "y"         : y_frames.tolist(),
        "speed"     : speed_frames.tolist(),
        "alt"       : alt_frames.tolist(),
        "mass"      : mass_frames.tolist(),
        "downrange" : downrange_frames.tolist(),
        "accel_g"   : accel_frames.tolist(),

        # Orbit traces
        "ellipse_x"      : x_ell.tolist(),
        "ellipse_y"      : y_ell.tolist(),
        "park_orbit_x"   : x_park_orb.tolist() if hasattr(x_park_orb, 'tolist') else list(x_park_orb),
        "park_orbit_y"   : y_park_orb.tolist() if hasattr(y_park_orb, 'tolist') else list(y_park_orb),
        "final_orbit_x"  : x_final_orb.tolist() if hasattr(x_final_orb, 'tolist') else list(x_final_orb),
        "final_orbit_y"  : y_final_orb.tolist() if hasattr(y_final_orb, 'tolist') else list(y_final_orb),
        "transfer_x"     : (x_tr.tolist() if isinstance(x_tr, np.ndarray) else list(x_tr)),
        "transfer_y"     : (y_tr.tolist() if isinstance(y_tr, np.ndarray) else list(y_tr)),
        "needs_hohmann"  : needs_hohmann,

        # Key positions
        "launch_x" : float(y_full[0][0]),
        "launch_y" : float(y_full[1][0]),
        "meco_x"   : float(x_f),
        "meco_y"   : float(y_f),
        "burn_x"   : float(circ["x_apo"]),
        "burn_y"   : float(circ["y_apo"]),

        "summary": {
            "stage_burnouts": [float(t_cut) for (_, _, t_cut) in rocket.timeline],
            "t_coast_start" : float(t_coast_start),
            "max_alt_km"    : float(tel["altitude"].max() / 1000),
            "max_speed_kms" : float(tel["speed"].max() / 1000),
            "max_q_kpa"     : float(tel["dyn_pres"].max() / 1000),
            "final_alt_km"  : float(tel["altitude"][-1] / 1000),
            "v_target_kms"  : float(v_circular(target_alt) / 1000),
            "delta_v_ms"    : float(circ["delta_v"]),
            "park_alt_km"   : float(parking_alt / 1000),
            "target_alt_km" : float(target_alt / 1000),
            "T_orbit_min"   : float(T_orbit / 60),
            "ecc_meco"      : float(el_meco["e"]),
            "ecc_final"     : float(circ["elements_final"]["e"]),
            "apo_km"        : float(el_meco["alt_apoapsis"] / 1000),
            "peri_km"       : float(el_meco["alt_periapsis"] / 1000),
            "needs_hohmann" : needs_hohmann,
            "transfer_dv1"     : float(tr["dv1"]) if tr else 0,
            "transfer_dv2"     : float(tr["dv2"]) if tr else 0,
            "transfer_dv_total": float(tr["dv_total"]) if tr else 0,
            "transfer_time_min": float(tr["T_transfer"] / 60) if tr else 0,
        },
    }

    return jsonify(_sanitize(_jsonify_arrays(result)))


if __name__ == "__main__":
    app.run(debug=True, port=5000)