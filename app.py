import numpy as np
from flask import Flask, render_template, request, jsonify

from constants   import Mu, Re, MoonOrbitR, MuMoon, MoonPeriod
from vehicle     import Rocket, Stage, PEGGuidance
from solver      import run_simulation, get_telemetry, run_coast, run_reentry
from orbital     import compute_orbital_elements, circularize, state_at_apoapsis, propagate_orbit, hohmann_transfer, get_moon_position, get_moon_velocity, set_moon_phase
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
    oms_dv_budget = float(cfg.get("oms_dv_budget", 2500))   # m/s — payload/upper-stage
                                                             # maneuvering propellant budget
    maneuver_cfg = cfg.get("second_maneuver") or {}
    reentry_cfg  = cfg.get("reentry") or {}
    tli_cfg      = cfg.get("tli") or {}
    # The requested display-orbit count belongs only to the last stable
    # orbit. Any enabled post-orbit burn starts immediately after insertion.
    final_orbit_count = n_orbits if not (
        maneuver_cfg.get("enabled") or reentry_cfg.get("enabled") or tli_cfg.get("enabled")
    ) else 0.5

    guidance = PEGGuidance(
        t_vertical      = float(np.clip(float(cfg.get("t_vertical", 20)), 5, 30)),
        target_altitude = target_alt,
    )
    rocket = Rocket(
        stages       = stages,
        payload_mass = float(cfg.get("payload_mass", 22800)),
        guidance     = guidance,
    )

    print(f"Target: {target_alt/1000:.0f} km | t_end: {rocket.timeline[-1][2]*1.2:.0f}s")
    print(f"  second_maneuver.enabled={maneuver_cfg.get('enabled')}  "
          f"tli.enabled={tli_cfg.get('enabled')} (target_apoapsis_km={tli_cfg.get('target_apoapsis_km')})  "
          f"reentry.enabled={reentry_cfg.get('enabled')}  oms_dv_budget={oms_dv_budget}")

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

    # PEG can cut engines off before a stage's propellant is fully spent
    # (e.g. an overpowered vehicle reaching its parking orbit early), so the
    # actual MECO time may fall mid-stage rather than at its nominal,
    # full-propellant cutoff. Reconstruct the per-stage burnout list — and
    # the leftover propellant, if any — from what actually happened.
    meco_time      = float(t_asc[-1])
    stage_burnouts = []
    prop_margin_kg = 0.0
    for stage, t_ign, t_cut in rocket.timeline:
        if meco_time <= t_ign:
            break
        stage_burnouts.append(min(t_cut, meco_time))
        if meco_time < t_cut:
            burned_frac    = (meco_time - t_ign) / (t_cut - t_ign)
            prop_margin_kg = stage.prop_mass * (1 - burned_frac)
            break

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
    # PEG always inserts into a low parking orbit; every materially different
    # selected target therefore needs a transfer, including a 400-km LEO.
    needs_hohmann = abs(target_alt - parking_alt) > 5e3
    transfer      = hohmann_transfer(parking_alt, target_alt) if needs_hohmann else None
    tr            = transfer  # always defined — None if no Hohmann

    if needs_hohmann and tr is not None:
        # tr is narrowed to a plain dict (not Optional) for the rest of this block

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
        t_tgt_end = t_trans_end + final_orbit_count * T_tgt
        if final_orbit_count:
            t_tgt, y_tgt = run_coast(state_tgt, t_trans_end, t_tgt_end)
        else:
            t_tgt, y_tgt = np.array([t_trans_end]), np.array(state_tgt, dtype=float).reshape(4, 1)

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
        t_orb_end   = t_apo + final_orbit_count * T_orbit
        if final_orbit_count:
            t_orbit, y_orbit = run_coast(state_circ, t_apo, t_orb_end)
        else:
            t_orbit, y_orbit = np.array([t_apo]), np.array(state_circ, dtype=float).reshape(4, 1)

        t_full = np.concatenate([t_asc, t_to_apo, t_orbit])
        y_full = np.hstack([y_asc, y_to_apo, y_orbit])
        t_coast_start = t_apo

        x_ell,  y_ell  = propagate_orbit(el_meco, above_surface_only=True)
        x_final_orb, y_final_orb = propagate_orbit(circ["elements_final"])
        x_park_orb = x_final_orb   # same orbit
        y_park_orb = y_final_orb
        x_tr = y_tr = []

    # ════════════════════════════════════════════
    # OMS Δv budget bookkeeping
    # ════════════════════════════════════════════
    # Every burn after MECO (circularization, the Hohmann transfer's two
    # burns, and now an optional second maneuver) has so far been modeled
    # as a "free" instantaneous velocity change — but by the time PEG cuts
    # engines off at MECO, the ascent stages have no propellant left (PEG
    # deliberately uses all of it to hit the parking orbit precisely). None
    # of these burns are actually free. Rather than track propellant mass
    # stage-by-stage for burns that happen after staging is already done,
    # the payload/upper stage gets a single Δv budget (m/s) — the same way
    # real satellites and kick stages are specified (a total maneuvering
    # capacity), independent of the launch vehicle's own propellant.
    oms_baseline_cost = abs(circ["delta_v"])
    if needs_hohmann and tr is not None:
        oms_baseline_cost += abs(tr["dv1"]) + abs(tr["dv2"])
    oms_over_budget = oms_baseline_cost > oms_dv_budget

    # ════════════════════════════════════════════
    # PHASE 4 — Optional second maneuver (raise/lower orbit)
    # ════════════════════════════════════════════
    # A generic "apply a delta-v at the end of the current trajectory, then
    # coast in the resulting orbit" building block — deliberately generic
    # rather than special-cased to Hohmann, since reentry (a retrograde
    # burn) and a future Trans-Lunar Injection (a large prograde burn) are
    # both just specific applications of the same mechanism.
    maneuver = maneuver_cfg
    x_maneuver_orb = y_maneuver_orb = []
    t_maneuver = None
    maneuver_dv_requested = 0.0
    maneuver_dv_applied   = 0.0
    if maneuver and maneuver.get("enabled"):
        dv_requested = float(maneuver.get("delta_v", 0))
        wait_s       = float(maneuver.get("wait_min", 0)) * 60.0

        # Clip the requested burn to whatever's left of the OMS budget
        # after circularization/Hohmann already spent their share. If the
        # baseline alone already blew the budget, no Δv is left at all.
        oms_remaining = max(0.0, oms_dv_budget - oms_baseline_cost)
        dv_maneuver   = float(np.clip(dv_requested, -oms_remaining, oms_remaining))
        maneuver_dv_requested = dv_requested
        maneuver_dv_applied   = dv_maneuver

        # Coast a bit longer in the CURRENT orbit first if requested, so the
        # burn doesn't always have to happen right where the initial coast
        # already ended.
        if wait_s > 0:
            state_pre = y_full[:, -1]
            t_wait, y_wait = run_coast(state_pre, t_full[-1], t_full[-1] + wait_s)
            t_full = np.concatenate([t_full, t_wait])
            y_full = np.hstack([y_full, y_wait])

        t_maneuver = float(t_full[-1])
        x_m, y_m, vx_m, vy_m = y_full[:, -1]
        v_mag = np.hypot(vx_m, vy_m)

        # Prograde burn (positive dv raises the opposite apsis, negative
        # lowers it) — velocity direction scaled up/down, direction unchanged
        # unless dv_maneuver is large/negative enough to reverse it (not
        # physically meaningful here, so it's left as-is; the UI keeps the
        # delta-v within a sane range relative to current orbital speed).
        scale = (v_mag + dv_maneuver) / v_mag if v_mag > 0 else 1.0
        vx_new, vy_new = vx_m * scale, vy_m * scale

        elements_new = compute_orbital_elements(x_m, y_m, vx_new, vy_new)
        T_new        = elements_new["T"]
        # Show the same number of complete post-burn orbits requested in the
        # configuration.  The previous 0.5 multiplier truncated this phase.
        t_man_end    = t_maneuver + n_orbits * T_new
        t_man, y_man = run_coast([x_m, y_m, vx_new, vy_new], t_maneuver, t_man_end)

        t_full = np.concatenate([t_full, t_man])
        y_full = np.hstack([y_full, y_man])

        x_maneuver_orb, y_maneuver_orb = propagate_orbit(elements_new)

    # ════════════════════════════════════════════
    # PHASE 4b — Optional Trans-Lunar Injection (TLI)
    # ════════════════════════════════════════════
    # A prograde burn toward a target apoapsis (defaulting to the Moon's
    # mean distance, 384,400 km), synced so the Moon is ACTUALLY there when
    # the spacecraft arrives (set_moon_phase — otherwise the trajectory
    # reaches the right distance at the wrong time, and the Moon is nowhere
    # nearby), followed by a lunar orbit insertion (LOI) burn, 1.5 orbits
    # around the Moon, and a trans-Earth injection (TEI) burn heading back.
    x_tli_orb = y_tli_orb = []
    t_tli = None
    tli_dv_requested = 0.0
    tli_dv_applied = 0.0
    tli_transit_days = None
    t_loi = None
    loi_dv_requested = 0.0
    loi_dv_applied = 0.0
    t_tei = None
    tei_dv_requested = 0.0
    tei_dv_applied = 0.0
    lunar_orbit_alt_km = None
    if tli_cfg and tli_cfg.get("enabled"):
        target_apoapsis_km = float(tli_cfg.get("target_apoapsis_km", 384400))
        wait_s = float(tli_cfg.get("wait_min", 0)) * 60.0

        if wait_s > 0:
            state_pre = y_full[:, -1]
            t_wait, y_wait = run_coast(state_pre, t_full[-1], t_full[-1] + wait_s)
            t_full = np.concatenate([t_full, t_wait])
            y_full = np.hstack([y_full, y_wait])

        t_tli = float(t_full[-1])
        x_t, y_t, vx_t, vy_t = y_full[:, -1]
        r_current = np.hypot(x_t, y_t)
        r_target  = Re + target_apoapsis_km * 1000.0
        v_mag_t   = np.hypot(vx_t, vy_t)

        a_transfer   = 0.5 * (r_current + r_target)
        v_circ_here  = np.sqrt(Mu / r_current)
        v_transfer   = np.sqrt(Mu * (2.0 / r_current - 1.0 / a_transfer))
        tli_dv_requested = max(0.0, v_transfer - v_circ_here)

        already_spent_tli = oms_baseline_cost + abs(maneuver_dv_applied)
        oms_remaining_tli = max(0.0, oms_dv_budget - already_spent_tli)
        tli_dv_applied = min(tli_dv_requested, oms_remaining_tli)

        scale_t = (v_mag_t + tli_dv_applied) / v_mag_t if v_mag_t > 0 else 1.0
        vx_tli, vy_tli = vx_t * scale_t, vy_t * scale_t

        elements_tli = compute_orbital_elements(x_t, y_t, vx_tli, vy_tli)
        T_tli = elements_tli["T"]
        t_tli_end = t_tli + 0.5 * T_tli
        tli_transit_days = float(0.5 * T_tli / 86400.0)

        # Sync the Moon's phase so it's actually at the transfer ellipse's
        # apoapsis when the spacecraft gets there. For a prograde burn from
        # a near-circular orbit, the burn point becomes the new ellipse's
        # PERIAPSIS, so apoapsis sits at burn_angle + 180°.
        apoapsis_angle = np.arctan2(y_t, x_t) + np.pi
        moon_angle_unphased = 2 * np.pi * (t_tli_end / MoonPeriod)
        phase0 = apoapsis_angle - moon_angle_unphased
        set_moon_phase(phase0)

        t_tr, y_tr2 = run_coast([x_t, y_t, vx_tli, vy_tli], t_tli, t_tli_end)
        t_full = np.concatenate([t_full, t_tr])
        y_full = np.hstack([y_full, y_tr2])

        x_tli_orb, y_tli_orb = propagate_orbit(elements_tli)

        # ── Lunar Orbit Insertion (LOI) ──
        # Whatever the real closest-approach distance turns out to be (this
        # simplified patched-two-body model can't precisely target a
        # specific altitude the way real mission planning does), circularize
        # there — same math as every other circularization burn in this
        # app, just relative to the MOON's gravity and motion instead of
        # Earth's.
        t_loi = float(t_full[-1])
        x_a, y_a, vx_a, vy_a = y_full[:, -1]
        xm, ym = get_moon_position(t_loi)
        vxm, vym = get_moon_velocity(t_loi)
        dx, dy   = x_a - xm, y_a - ym
        dvx, dvy = vx_a - vxm, vy_a - vym
        r_rel     = np.hypot(dx, dy)
        speed_rel = np.hypot(dvx, dvy)
        lunar_orbit_alt_km = float(r_rel / 1000.0)   # informational — Moon radius not modeled as a body to collide with

        v_circ_moon = np.sqrt(MuMoon / r_rel) if r_rel > 0 else 0.0
        loi_dv_requested = max(0.0, speed_rel - v_circ_moon)
        already_spent_loi = already_spent_tli + tli_dv_applied
        remaining_loi = max(0.0, oms_dv_budget - already_spent_loi)
        loi_dv_applied = min(loi_dv_requested, remaining_loi)

        scale_loi = (speed_rel - loi_dv_applied) / speed_rel if speed_rel > 0 else 1.0
        new_dvx, new_dvy = dvx * scale_loi, dvy * scale_loi
        y_full[2, -1] = vxm + new_dvx
        y_full[3, -1] = vym + new_dvy

        # ── Coast 1.5 orbits around the Moon ──
        T_lunar = 2 * np.pi * np.sqrt(r_rel**3 / MuMoon) if r_rel > 0 else 0.0
        t_lunar_end = t_loi + 1.5 * T_lunar
        t_lo, y_lo = run_coast(y_full[:, -1], t_loi, t_lunar_end)
        t_full = np.concatenate([t_full, t_lo])
        y_full = np.hstack([y_full, y_lo])

        # ── Trans-Earth Injection (TEI) ──
        # Symmetric with LOI in spirit (burn relative to the Moon), but
        # targeting a modest margin ABOVE local escape velocity so the
        # spacecraft actually breaks free of the Moon's gravity well and
        # heads back out, rather than just loosening the current orbit.
        t_tei = float(t_full[-1])
        x_b, y_b, vx_b, vy_b = y_full[:, -1]
        xm2, ym2 = get_moon_position(t_tei)
        vxm2, vym2 = get_moon_velocity(t_tei)
        dxb, dyb   = x_b - xm2, y_b - ym2
        dvxb, dvyb = vx_b - vxm2, vy_b - vym2
        r_rel2     = np.hypot(dxb, dyb)
        speed_rel2 = np.hypot(dvxb, dvyb)

        v_escape_moon = np.sqrt(2.0 * MuMoon / r_rel2) if r_rel2 > 0 else 0.0
        v_tei_target  = v_escape_moon * 1.05   # 5% margin over parabolic escape
        tei_dv_requested = max(0.0, v_tei_target - speed_rel2)
        already_spent_tei = already_spent_loi + loi_dv_applied
        remaining_tei = max(0.0, oms_dv_budget - already_spent_tei)
        tei_dv_applied = min(tei_dv_requested, remaining_tei)

        scale_tei = (speed_rel2 + tei_dv_applied) / speed_rel2 if speed_rel2 > 0 else 1.0
        new_dvxb, new_dvyb = dvxb * scale_tei, dvyb * scale_tei
        y_full[2, -1] = vxm2 + new_dvxb
        y_full[3, -1] = vym2 + new_dvyb

        # ── Coast back toward Earth ──
        # A full, precisely-targeted Earth-return trajectory (aiming for a
        # specific safe reentry corridor) is a much harder targeting problem
        # than this simplified patched-two-body model attempts — this just
        # coasts under real Earth+Moon gravity for roughly the same duration
        # as the outbound transit, showing a physically genuine (if not
        # precisely aimed) return leg.
        t_return_end = t_tei + 0.5 * T_tli
        t_ret, y_ret = run_coast(y_full[:, -1], t_tei, t_return_end)
        t_full = np.concatenate([t_full, t_ret])
        y_full = np.hstack([y_full, y_ret])

    # ════════════════════════════════════════════
    # PHASE 5 — Optional deorbit burn and ballistic reentry
    # ════════════════════════════════════════════
    reentry = reentry_cfg
    t_descent_burn = None        # time of the optional "return to parking orbit" burn
    t_reentry_circ = None        # time of the optional circularization-at-parking burn
    t_reentry = None             # time of the actual atmosphere-targeting deorbit burn
    reentry_descent_dv = 0.0
    reentry_circ_dv = 0.0
    dv_descent_requested = 0.0
    dv_circ_requested = 0.0
    reentry_dv_requested = 0.0
    reentry_dv_applied = 0.0
    reentry_impacted = False
    if reentry and reentry.get("enabled"):
        wait_s = float(reentry.get("wait_min", 0)) * 60.0
        if wait_s > 0:
            t_wait, y_wait = run_coast(y_full[:, -1], t_full[-1], t_full[-1] + wait_s)
            t_full = np.concatenate([t_full, t_wait])
            y_full = np.hstack([y_full, y_wait])

        already_spent = oms_baseline_cost + abs(maneuver_dv_applied) + tli_dv_applied + loi_dv_applied + tei_dv_applied
        x_h, y_h, vx_h, vy_h = y_full[:, -1]
        r_high = np.hypot(x_h, y_h)
        r_park_target = Re + circ["alt_circular"]

        # Reserve a chunk of whatever OMS budget is left for the ACTUAL
        # deorbit burn before spending anything on the return-to-parking
        # sequence below. 250 m/s comfortably covers a real deorbit burn
        # from a circular LEO-ish parking orbit.
        DEORBIT_RESERVE = 250.0
        return_budget = max(0.0, oms_dv_budget - already_spent - DEORBIT_RESERVE)

        # A single burn straight down to the surface from well above the
        # parking orbit (e.g. after a Hohmann transfer to MEO/GEO, or a
        # second maneuver that raised the orbit) would enter the atmosphere
        # at an extremely high, unrealistic speed — the vis-viva speed for
        # a direct fall from that altitude is far higher than a real
        # deorbit's ~7.5-8 km/s entry interface. Real deorbits from well
        # above LEO first return to a low parking-type orbit, THEN perform
        # the actual (much smaller) atmospheric entry burn from there.
        needs_return_trip = r_high > 1.5 * r_park_target
        dv_descent_requested = 0.0
        if needs_return_trip:
            speed_h = np.hypot(vx_h, vy_h)
            a_descent = 0.5 * (r_high + r_park_target)
            v_descent = np.sqrt(Mu * (2.0 / r_high - 1.0 / a_descent))
            dv_descent_requested = max(0.0, speed_h - v_descent)

        # Only actually ATTEMPT the two-burn return (descend, then
        # circularize) if the budget covers at least the descent burn in
        # full. Committing to it on a smaller budget used to silently apply
        # 0 m/s to both burns — leaving the vehicle exactly where it
        # started, at the ORIGINAL high orbit — while the code still acted
        # as if it were back at the parking orbit for the final "deorbit"
        # burn afterward. That burn was then computed (correctly, for
        # wherever the vehicle actually was) as a huge GEO-direct-to-surface
        # Δv, of which only a tiny sliver could be afforded — nowhere near
        # enough to bring perigee down, so it just coasted for a lap and
        # stopped without ever reentering. Falling back to a single
        # best-effort burn (below) at least puts 100% of what's available
        # toward lowering perigee as much as possible from wherever the
        # vehicle really is.
        if needs_return_trip and return_budget >= dv_descent_requested:
            # Burn 1 — drop periapsis down to the parking-orbit altitude.
            t_descent_burn = float(t_full[-1])
            speed_h = np.hypot(vx_h, vy_h)
            dv_descent_applied = dv_descent_requested   # fully affordable, per the check above
            return_budget -= dv_descent_applied
            already_spent += dv_descent_applied
            reentry_descent_dv = dv_descent_applied

            scale = max(0.0, speed_h - dv_descent_applied) / speed_h if speed_h > 0 else 1.0
            vx_d, vy_d = vx_h * scale, vy_h * scale

            elements_descent = compute_orbital_elements(x_h, y_h, vx_d, vy_d)
            T_descent   = elements_descent["T"]
            t_desc_end  = t_descent_burn + 0.5 * T_descent
            t_desc, y_desc = run_coast([x_h, y_h, vx_d, vy_d], t_descent_burn, t_desc_end)
            t_full = np.concatenate([t_full, t_desc])
            y_full = np.hstack([y_full, y_desc])

            # Burn 2 — circularize AT the parking-orbit altitude. Without
            # this, the vehicle is only passing through periapsis of the
            # big descent ellipse — still moving at that ellipse's periapsis
            # speed (well above local circular speed; for a GEO-origin
            # descent this is ~10 km/s vs. ~7.8 km/s circular), so "back at
            # the parking orbit" wouldn't actually mean a gentle circular
            # orbit yet without flattening it out here.
            t_circ_burn = float(t_full[-1])
            x_p3, y_p3, vx_p3, vy_p3 = y_full[:, -1]
            r_p3 = np.hypot(x_p3, y_p3)
            speed_p3 = np.hypot(vx_p3, vy_p3)
            v_circ_p3 = np.sqrt(Mu / r_p3)
            dv_circ_requested = max(0.0, speed_p3 - v_circ_p3)
            dv_circ_applied = min(dv_circ_requested, return_budget)
            return_budget -= dv_circ_applied
            already_spent += dv_circ_applied
            reentry_circ_dv = dv_circ_applied
            t_reentry_circ  = t_circ_burn

            scale2 = max(0.0, speed_p3 - dv_circ_applied) / speed_p3 if speed_p3 > 0 else 1.0
            v_circ_applied = speed_p3 * scale2
            # Snap to a purely tangential direction rather than just scaling
            # the existing velocity vector: the coast that got us here only
            # approximates periapsis (bounded by run_coast's own timestep),
            # so there's a small residual radial component left over — left
            # unscaled, that turns "circularize" into a slightly elliptical
            # orbit instead of a clean circle.
            tx3, ty3 = -y_p3 / r_p3, x_p3 / r_p3
            y_full[2, -1] = v_circ_applied * tx3
            y_full[3, -1] = v_circ_applied * ty3

            # A short arc (not a full lap) before the final deorbit burn —
            # just enough that the two burn markers don't sit on top of each
            # other in the 3D view. One parking-orbit revolution here would
            # be a needless extra lap before anything visibly happens.
            T_park_circ  = 2 * np.pi * np.sqrt(r_p3**3 / Mu)
            t_coast_gap  = min(120.0, 0.03 * T_park_circ)
            t_gap, y_gap = run_coast(y_full[:, -1], t_full[-1], t_full[-1] + t_coast_gap)
            t_full = np.concatenate([t_full, t_gap])
            y_full = np.hstack([y_full, y_gap])
        elif needs_return_trip:
            # Can't even afford the descent burn in full — don't pretend to
            # circularize at a parking orbit we never reached. Put 100% of
            # whatever's left toward a single best-effort retrograde burn
            # from wherever the vehicle actually is (still the original high
            # orbit), maximizing how far perigee drops even if it can't
            # reach the ground. The reserve is folded back in here too,
            # since there's no separate "at parking orbit" burn left to
            # protect it for.
            t_descent_burn = float(t_full[-1])
            dv_descent_applied = min(dv_descent_requested, return_budget + DEORBIT_RESERVE)
            already_spent += dv_descent_applied
            reentry_descent_dv = dv_descent_applied

            speed_h = np.hypot(vx_h, vy_h)
            scale = max(0.0, speed_h - dv_descent_applied) / speed_h if speed_h > 0 else 1.0
            y_full[2, -1] = vx_h * scale
            y_full[3, -1] = vy_h * scale

        # Actual deorbit burn — from (roughly) parking-orbit altitude, drop
        # the opposite apsis into the atmosphere for a realistic entry speed.
        # Uses whatever's left of the budget PLUS the reserve set aside
        # above, so this burn is the last one to ever come up short.
        remaining = max(0.0, oms_dv_budget - already_spent)
        reentry_perigee = Re
        x_r, y_r, vx_r, vy_r = y_full[:, -1]
        speed = np.hypot(vx_r, vy_r)
        r_r = np.hypot(x_r, y_r)
        a_deorbit = 0.5 * (r_r + reentry_perigee)
        target_speed = np.sqrt(Mu * (2.0 / r_r - 1.0 / a_deorbit))
        reentry_dv_requested = max(0.0, speed - target_speed)
        reentry_dv_applied = min(reentry_dv_requested, remaining)
        scale = max(0.0, speed - reentry_dv_applied) / speed if speed > 0 else 1.0
        state_deorbit = [x_r, y_r, vx_r * scale, vy_r * scale]
        elements_deorbit = compute_orbital_elements(*state_deorbit)

        t_reentry = float(t_full[-1])
        # Give the ballistic descent at most ONE extra orbital period beyond
        # a 30-minute floor to actually intersect the atmosphere and impact
        # — more than that is just needless extra laps if the burn wasn't
        # enough to bring it down.
        coast_limit = t_reentry + max(1800.0, elements_deorbit["T"])
        t_re, y_re, reentry_impacted = run_reentry(
            state_deorbit, t_reentry, coast_limit,
            mass=rocket.payload_mass, Cd=1.2, A=max(1.0, stages[-1].A * 0.25),
        )
        t_full = np.concatenate([t_full, t_re])
        y_full = np.hstack([y_full, y_re])

    # List of every OMS burn that happens, in order, with when it happens —
    # lets the frontend compute "how much OMS budget is left" at any point
    # in time (not just the final total), for the HUD's Propellant readout
    # during coast phases (no ascent stage is active then, but the payload
    # still has OMS Δv it hasn't spent yet).
    oms_burns = [{"t": float(t_apo), "dv": float(abs(circ["delta_v"])), "label": "Circularization"}]
    if needs_hohmann and tr is not None:
        oms_burns.append({"t": float(t_park_end), "dv": float(abs(tr["dv1"])), "label": "Transfer injection"})
        oms_burns.append({"t": float(t_coast_start), "dv": float(abs(tr["dv2"])), "label": "Circularization at target"})
    if t_maneuver is not None and abs(maneuver_dv_applied) > 0:
        oms_burns.append({"t": float(t_maneuver), "dv": float(abs(maneuver_dv_applied)), "label": "Second maneuver"})
    if t_tli is not None and tli_dv_applied > 0:
        oms_burns.append({"t": float(t_tli), "dv": float(tli_dv_applied), "label": "Trans-Lunar Injection"})
    if t_loi is not None and loi_dv_applied > 0:
        oms_burns.append({"t": float(t_loi), "dv": float(loi_dv_applied), "label": "Lunar orbit insertion"})
    if t_tei is not None and tei_dv_applied > 0:
        oms_burns.append({"t": float(t_tei), "dv": float(tei_dv_applied), "label": "Trans-Earth injection"})
    if t_descent_burn is not None and reentry_descent_dv > 0:
        oms_burns.append({"t": float(t_descent_burn), "dv": float(reentry_descent_dv), "label": "Descent to parking orbit"})
    if t_reentry_circ is not None and reentry_circ_dv > 0:
        oms_burns.append({"t": float(t_reentry_circ), "dv": float(reentry_circ_dv), "label": "Circularize at parking orbit"})
    if t_reentry is not None and reentry_dv_applied > 0:
        oms_burns.append({"t": float(t_reentry), "dv": float(reentry_dv_applied), "label": "Deorbit burn"})

    # Δv burn markers for the 3D view — position, magnitude, and whether
    # each burn is prograde (speeds up, raises the opposite apsis) or
    # retrograde (slows down, lowers it), so they can be drawn with
    # distinct marker styles.
    burn_markers = [{
        "x": float(circ["x_apo"]), "y": float(circ["y_apo"]),
        "dv": float(circ["delta_v"]), "label": "Circularization",
        "retrograde": bool(circ["delta_v"] < 0),
    }]
    if needs_hohmann and tr is not None:
        burn_markers.append({
            "x": float(x_p), "y": float(y_p),
            "dv": float(tr["dv1"]), "label": "Transfer injection",
            "retrograde": bool(tr["dv1"] < 0),
        })
        burn_markers.append({
            "x": float(x_ta), "y": float(y_ta),
            "dv": float(tr["dv2"]), "label": "Circularization at target",
            "retrograde": bool(tr["dv2"] < 0),
        })
    if t_maneuver is not None and abs(maneuver_dv_applied) > 0:
        burn_markers.append({
            "x": float(x_m), "y": float(y_m),
            "dv": float(maneuver_dv_applied), "label": "Second maneuver",
            "retrograde": bool(maneuver_dv_applied < 0),
        })
    if t_tli is not None and tli_dv_applied > 0:
        burn_markers.append({
            "x": float(x_t), "y": float(y_t),
            "dv": float(tli_dv_applied), "label": "Trans-Lunar Injection",
            "retrograde": False,
        })
    if t_loi is not None and loi_dv_applied > 0:
        burn_markers.append({
            "x": float(x_a), "y": float(y_a),
            "dv": float(-loi_dv_applied), "label": "Lunar orbit insertion",
            "retrograde": True,
        })
    if t_tei is not None and tei_dv_applied > 0:
        burn_markers.append({
            "x": float(x_b), "y": float(y_b),
            "dv": float(tei_dv_applied), "label": "Trans-Earth injection",
            "retrograde": False,
        })
    if t_descent_burn is not None and reentry_descent_dv > 0:
        burn_markers.append({
            "x": float(x_h), "y": float(y_h),
            "dv": float(-reentry_descent_dv), "label": "Descent to parking orbit",
            "retrograde": True,
        })
    if t_reentry_circ is not None and reentry_circ_dv > 0:
        burn_markers.append({
            "x": float(x_p3), "y": float(y_p3),
            "dv": float(-reentry_circ_dv), "label": "Circularize at parking orbit",
            "retrograde": True,
        })
    if t_reentry is not None and reentry_dv_applied > 0:
        burn_markers.append({
            "x": float(x_r), "y": float(y_r),
            "dv": float(-reentry_dv_applied), "label": "Deorbit burn",
            "retrograde": True,
        })

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
    # A SINGLE fixed time step for the entire mission, no exceptions per
    # phase. Any two frames anywhere in the animation are the same distance
    # apart in TIME, so on-screen distance-per-frame is always directly
    # proportional to real speed — no visible "speed up" at any phase
    # boundary (ascent/coast/Hohmann/target orbit/maneuver/reentry), because
    # there are no boundaries in the sampling at all.
    T_total = float(t_full[-1] - t_full[0])
    TARGET_TOTAL_FRAMES = 6000
    dt_uniform = max(1.0, T_total / TARGET_TOTAL_FRAMES) if T_total > 0 else 1.0
    t_frames = np.arange(t_full[0], t_full[-1] + dt_uniform, dt_uniform)
    t_frames = np.unique(np.append(t_frames, t_full[-1]))
    x_frames         = np.interp(t_frames, t_full, y_full[0])
    y_frames         = np.interp(t_frames, t_full, y_full[1])
    speed_frames     = np.interp(t_frames, t_full, tel["speed"])
    alt_frames       = np.interp(t_frames, t_full, tel["altitude"])
    mass_frames      = np.interp(t_frames, t_full, tel["mass"])
    downrange_frames = np.interp(t_frames, t_full, tel["downrange"])
    accel_frames     = np.interp(t_frames, t_full, tel["accel_g"])

    # Moon position at each displayed frame (for animating it moving along
    # its orbit), plus its full circular path as a static reference trace.
    # Only sent when TLI is actually in play — at every other mission scale
    # (LEO/MEO/GEO), including the Moon's ~384,400km-away reference orbit
    # would force the 3D view's camera to zoom out to lunar distances,
    # shrinking the actual mission trajectory down to an invisible speck.
    if tli_cfg and tli_cfg.get("enabled"):
        moon_x_frames, moon_y_frames = zip(*(get_moon_position(t) for t in t_frames))
        _moon_orbit_theta = np.linspace(0, 2 * np.pi, 200)
        moon_orbit_x = (MoonOrbitR * np.cos(_moon_orbit_theta)).tolist()
        moon_orbit_y = (MoonOrbitR * np.sin(_moon_orbit_theta)).tolist()
    else:
        moon_x_frames, moon_y_frames = [], []
        moon_orbit_x, moon_orbit_y = [], []

    # Active stage + remaining propellant fraction at each frame — used by
    # the HUD to show e.g. "Stage 2: 64% (18.2 t / 28.4 t)". None while
    # coasting between/after stages (no active stage burning propellant).
    active_stage_frames = []
    prop_frac_frames    = []
    for t in t_frames:
        stage, t_ign = rocket._get_active_stage(float(t))
        if stage is None:
            active_stage_frames.append(None)
            prop_frac_frames.append(None)
        else:
            idx = next(i for i, (s, _, _) in enumerate(rocket.timeline) if s is stage)
            remaining = stage.prop_mass - stage.mdot * (t - t_ign)
            frac = float(np.clip(remaining / stage.prop_mass, 0.0, 1.0))
            active_stage_frames.append(idx)
            prop_frac_frames.append(frac)

    result = {
        "t"         : t_frames.tolist(),
        "x"         : x_frames.tolist(),
        "y"         : y_frames.tolist(),
        "speed"     : speed_frames.tolist(),
        "alt"       : alt_frames.tolist(),
        "mass"      : mass_frames.tolist(),
        "downrange" : downrange_frames.tolist(),
        "accel_g"   : accel_frames.tolist(),
        "active_stage": active_stage_frames,
        "prop_frac"   : prop_frac_frames,

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
        "maneuver_x"     : (x_maneuver_orb.tolist() if isinstance(x_maneuver_orb, np.ndarray) else list(x_maneuver_orb)),
        "maneuver_y"     : (y_maneuver_orb.tolist() if isinstance(y_maneuver_orb, np.ndarray) else list(y_maneuver_orb)),
        "tli_x"          : (x_tli_orb.tolist() if isinstance(x_tli_orb, np.ndarray) else list(x_tli_orb)),
        "tli_y"          : (y_tli_orb.tolist() if isinstance(y_tli_orb, np.ndarray) else list(y_tli_orb)),
        "moon_x"         : list(moon_x_frames),
        "moon_y"         : list(moon_y_frames),
        "moon_orbit_x"   : moon_orbit_x,
        "moon_orbit_y"   : moon_orbit_y,

        # Key positions
        "launch_x" : float(y_full[0][0]),
        "launch_y" : float(y_full[1][0]),
        "meco_x"   : float(x_f),
        "meco_y"   : float(y_f),
        "burn_x"   : float(circ["x_apo"]),
        "burn_markers": burn_markers,
        "burn_y"   : float(circ["y_apo"]),

        "summary": {
            "stage_burnouts": stage_burnouts,
            "stage_prop_masses_kg": [float(s.prop_mass) for s, _, _ in rocket.timeline],
            "prop_margin_kg": float(prop_margin_kg),
            "oms_dv_budget"        : float(oms_dv_budget),
            "oms_baseline_cost"    : float(oms_baseline_cost),
            "oms_burns"            : oms_burns,
            "oms_over_budget"      : bool(oms_over_budget),
            "maneuver_dv_requested": float(maneuver_dv_requested),
            "maneuver_dv_applied"  : float(maneuver_dv_applied),
            "maneuver_limited"     : bool(abs(maneuver_dv_applied) < abs(maneuver_dv_requested) - 1e-6),
            "t_tli"             : t_tli,
            "tli_dv_requested"  : float(tli_dv_requested),
            "tli_dv_applied"    : float(tli_dv_applied),
            "tli_limited"       : bool(tli_dv_applied < tli_dv_requested - 1e-6),
            "tli_transit_days"  : tli_transit_days,
            "t_loi"             : t_loi,
            "loi_dv_requested"  : float(loi_dv_requested),
            "loi_dv_applied"    : float(loi_dv_applied),
            "lunar_orbit_alt_km": lunar_orbit_alt_km,
            "t_tei"             : t_tei,
            "tei_dv_requested"  : float(tei_dv_requested),
            "tei_dv_applied"    : float(tei_dv_applied),
            "t_apo"         : float(t_apo),
            "t_park_end"    : float(t_park_end) if needs_hohmann else None,
            "t_maneuver"    : t_maneuver,
            "t_reentry"     : t_reentry,
            "t_descent_burn": t_descent_burn,
            "reentry_descent_dv"  : float(reentry_descent_dv),
            "reentry_descent_limited": bool(reentry_descent_dv < dv_descent_requested - 1e-6),
            "t_reentry_circ": t_reentry_circ,
            "reentry_circ_dv"     : float(reentry_circ_dv),
            "reentry_circ_limited": bool(reentry_circ_dv < dv_circ_requested - 1e-6),
            "reentry_dv_requested": float(reentry_dv_requested),
            "reentry_dv_applied": float(reentry_dv_applied),
            "reentry_limited": bool(reentry_dv_applied < reentry_dv_requested - 1e-6),
            "reentry_any_limited": bool(
                (reentry_descent_dv < dv_descent_requested - 1e-6) or
                (reentry_circ_dv < dv_circ_requested - 1e-6) or
                (reentry_dv_applied < reentry_dv_requested - 1e-6)
            ),
            "reentry_impacted": bool(reentry_impacted),
            "t_coast_start" : float(t_coast_start),
            "max_alt_km"    : float(tel["altitude"].max() / 1000),
            "max_speed_kms" : float(tel["speed"].max() / 1000),
            # Max-Q is specifically an ASCENT term (peak aerodynamic load
            # during launch) — restricted to t <= MECO so an unrelated,
            # much larger dynamic pressure spike during reentry (a genuinely
            # different physical phase, at orbital-plus speeds) doesn't get
            # folded into the same number and misreported as launch max-Q.
            "max_q_kpa"     : float(tel["dyn_pres"][t_full <= meco_time].max() / 1000),
            "reentry_max_q_kpa": (
                float(tel["dyn_pres"][t_full >= t_reentry].max() / 1000)
                if t_reentry is not None else None
            ),
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