import numpy as np
from constants import Mu, Re

def compute_orbital_elements(x, y, vx, vy):
    """
    Computes classical orbital elements from a 2D Cartesian state vector.

    Parameters:
        x, y   : m   - Position components (origin at Earth's center)
        vx, vy : m/s - Velocity components

    Returns:
        dict with all orbital elements and derived quantities
    """
    r_vec = np.array([x, y])
    v_vec = np.array([vx, vy])

    r = np.linalg.norm(r_vec)
    v = np.linalg.norm(v_vec)

    # --- Specific orbital energy ---
    epsilon = v**2 / 2 - Mu / r       # J/kg - Negative means bound orbit

    # --- Semi-major axis ---
    a = -Mu / (2 * epsilon)            # m

    # --- Specific angular momentum (scalar in 2D) ---
    h = x * vy - y * vx               # m²/s

    # --- Eccentricity ---
    e = np.sqrt(1 + (2 * epsilon * h**2) / Mu**2)

    # --- Apoapsis and periapsis radii ---
    r_a = a * (1 + e)
    r_p = a * (1 - e)

    # --- Altitudes above surface ---
    alt_apoapsis  = r_a - Re
    alt_periapsis = r_p - Re

    # --- Orbital period ---
    T = 2 * np.pi * np.sqrt(a**3 / Mu)

    # --- Velocities at apoapsis and periapsis ---
    v_apoapsis  = h / r_a
    v_periapsis = h / r_p

    # --- Eccentricity vector (points toward periapsis) ---
    e_vec = (1/Mu) * ((v**2 - Mu/r) * r_vec - np.dot(r_vec, v_vec) * v_vec)

    # --- Argument of periapsis (angle of periapsis from +x axis) ---
    omega_peri = np.arctan2(e_vec[1], e_vec[0])

    # --- True anomaly ---
    e_vec_norm = e_vec / (np.linalg.norm(e_vec) + 1e-12)
    cos_nu     = np.clip(np.dot(e_vec_norm, r_vec / r), -1, 1)
    nu         = np.degrees(np.arccos(cos_nu))
    if np.cross(e_vec, r_vec) < 0:
        nu = 360 - nu

    return {
        "epsilon"       : epsilon,
        "a"             : a,
        "e"             : e,
        "h"             : h,
        "T"             : T,
        "r_apoapsis"    : r_a,
        "r_periapsis"   : r_p,
        "alt_apoapsis"  : alt_apoapsis,
        "alt_periapsis" : alt_periapsis,
        "v_apoapsis"    : v_apoapsis,
        "v_periapsis"   : v_periapsis,
        "true_anomaly"  : nu,
        "omega_peri"    : omega_peri,   # rad - Argument of periapsis
    }


def propagate_orbit(elements, n_points=1000, above_surface_only=False):
    """
    Generates the orbital ellipse in Cartesian coordinates.
    Uses the polar orbit equation and rotates by argument of periapsis.

    If above_surface_only=True, clips the ellipse to only show the
    portion above Earth's surface (r > Re). Points below are replaced
    with NaN so Plotly draws a gap instead of a line through the Earth.
    """
    a          = elements["a"]
    e          = elements["e"]
    h          = elements["h"]
    omega_peri = elements["omega_peri"]

    nu_arr = np.linspace(0, 2 * np.pi, n_points)
    r_arr  = (h**2 / Mu) / (1 + e * np.cos(nu_arr))

    # Perifocal frame
    x_peri = r_arr * np.cos(nu_arr)
    y_peri = r_arr * np.sin(nu_arr)

    # Rotate to inertial frame
    cos_w = np.cos(omega_peri)
    sin_w = np.sin(omega_peri)

    x_inertial = cos_w * x_peri - sin_w * y_peri
    y_inertial = sin_w * x_peri + cos_w * y_peri

    if above_surface_only:
        # Mask points below Earth surface with NaN
        below = r_arr < Re
        x_inertial = np.where(below, np.nan, x_inertial)
        y_inertial = np.where(below, np.nan, y_inertial)

    return x_inertial, y_inertial


def circularize(x, y, vx, vy):
    """
    Computes the Hohmann circularization burn at apoapsis.

    The rocket coasts from its current position to apoapsis, then fires
    a prograde burn to raise the periapsis to match the apoapsis altitude,
    resulting in a circular orbit.

    Parameters:
        x, y, vx, vy : current state at MECO

    Returns:
        dict with coast time, delta-V, and final orbital elements
    """
    elements = compute_orbital_elements(x, y, vx, vy)

    r_a    = elements["r_apoapsis"]    # m - Apoapsis radius
    v_a    = elements["v_apoapsis"]    # m/s - Speed at apoapsis (current ellipse)
    h      = elements["h"]
    T      = elements["T"]
    nu     = elements["true_anomaly"]  # deg - Current true anomaly

    # --- Coast time from current position to apoapsis ---
    # Time from periapsis to current position (Kepler's equation)
    a  = elements["a"]
    e  = elements["e"]
    nu_rad = np.radians(nu)

    # Eccentric anomaly at current position
    E_now = 2 * np.arctan(np.sqrt((1-e)/(1+e)) * np.tan(nu_rad/2))
    # Mean anomaly at current position
    M_now = E_now - e * np.sin(E_now)
    # Mean anomaly at apoapsis (ν=180°)
    M_apo = np.pi

    # Coast time = time to go from M_now to M_apo.
    # Using a plain (M_apo - M_now) % (2*pi) is fragile right around
    # apoapsis itself: if we're just a hair PAST it (e.g. MECO landed a few
    # degrees past the true anomaly of 180°, which can happen — engine
    # cutoff is checked periodically, not at infinite resolution), the
    # modulo wraps almost all the way around to nearly a FULL orbital
    # period, computing "coast to the next apoapsis" instead of recognizing
    # we're already basically there. Using the signed difference wrapped to
    # (-pi, pi] and snapping small differences (either side) to zero avoids
    # that — matching the physical reality of "we're at the apex" as
    # PEG intends, regardless of which side of the exact peak MECO fell on.
    n = 2 * np.pi / T                      # Mean motion (rad/s)
    diff = (M_apo - M_now + np.pi) % (2 * np.pi) - np.pi   # signed, in (-pi, pi]
    APOAPSIS_SNAP_RAD = np.radians(45)     # within ~45° of apex counts as "there"
    snapped = abs(diff) < APOAPSIS_SNAP_RAD
    if snapped:
        t_coast = 0.0
    else:
        delta_M = diff % (2 * np.pi)
        t_coast = delta_M / n              # s

    # --- Circularization delta-V ---
    if snapped:
        # Use the REAL radius/speed at the current (snapped) position,
        # not the idealized exact-apoapsis values — consistent with using
        # the real position for x_apo/y_apo below.
        r_a_eff = np.sqrt(x**2 + y**2)
        v_a_eff = np.sqrt(vx**2 + vy**2)
    else:
        r_a_eff = r_a
        v_a_eff = v_a
    v_circ  = np.sqrt(Mu / r_a_eff)   # m/s
    delta_v = v_circ - v_a_eff        # m/s - Prograde burn at apoapsis

    # --- Final circular orbit elements ---
    # After burn: periapsis raised to apoapsis altitude → circular orbit
    # State at apoapsis after burn: position at r_a, velocity = v_circ tangentially
    if snapped:
        # We've snapped t_coast to 0 — meaning downstream code treats the
        # CURRENT position (wherever the ascent/coast trajectory actually
        # ended up, up to ~45° of true anomaly from the exact apex) as "the"
        # apoapsis. The circularization point must match that same real
        # position, not the mathematically exact nu=180° point (which the
        # trajectory doesn't actually pass through when snapped) — using
        # the exact point instead created a visible backward jump where the
        # animated trajectory teleported a few degrees "backward" along the
        # orbit right as the parking-orbit coast phase began.
        r_here = r_a_eff
        tx, ty = -y / r_here, x / r_here  # tangential unit vector, prograde
        x_apo, y_apo   = x, y
        vx_apo, vy_apo = v_circ * tx, v_circ * ty
    else:
        omega_peri = elements["omega_peri"]
        # Apoapsis is at angle omega_peri + 180°
        theta_apo = omega_peri + np.pi
        x_apo  =  r_a * np.cos(theta_apo)
        y_apo  =  r_a * np.sin(theta_apo)
        # Velocity is perpendicular to position (tangential) at apoapsis
        vx_apo = -v_circ * np.sin(theta_apo)
        vy_apo =  v_circ * np.cos(theta_apo)

    elements_final = compute_orbital_elements(x_apo, y_apo, vx_apo, vy_apo)

    return {
        "t_coast"        : t_coast,           # s   - Coast time to apoapsis
        "delta_v"        : delta_v,           # m/s - Required delta-V
        "alt_circular"   : r_a_eff - Re,      # m   - Circular orbit altitude
        "v_circular"     : v_circ,            # m/s - Circular orbital speed
        "e_final"        : elements_final["e"],
        "elements_final" : elements_final,
        "x_apo"          : x_apo,            # m   - Position at apoapsis
        "y_apo"          : y_apo,
    }


def state_at_apoapsis(circ):
    """
    Returns the [x, y, vx, vy] state at the apoapsis point
    after the circularization burn, ready for coast propagation.
    Velocity is purely tangential (perpendicular to position vector).
    """
    x_apo  = circ["x_apo"]
    y_apo  = circ["y_apo"]
    v_circ = circ["v_circular"]

    r  = np.sqrt(x_apo**2 + y_apo**2)
    tx = -y_apo / r    # Tangential unit vector x
    ty =  x_apo / r    # Tangential unit vector y

    return [x_apo, y_apo, v_circ * tx, v_circ * ty]


def hohmann_transfer(alt_parking, alt_target):
    """
    Computes a Hohmann transfer from a circular parking orbit
    to a circular target orbit.

    Parameters:
        alt_parking : m - Parking orbit altitude
        alt_target  : m - Target orbit altitude

    Returns:
        dict with both burns, transfer time, and transfer ellipse elements
    """
    r1 = Re + alt_parking    # m - Parking orbit radius
    r2 = Re + alt_target     # m - Target orbit radius

    # Circular velocities
    v1 = np.sqrt(Mu / r1)   # m/s - Parking orbit speed
    v2 = np.sqrt(Mu / r2)   # m/s - Target orbit speed

    # Transfer ellipse
    a_tr = (r1 + r2) / 2
    e_tr = (r2 - r1) / (r2 + r1)
    h_tr = np.sqrt(Mu * a_tr * (1 - e_tr**2))

    # Velocities on transfer ellipse at perigee and apogee
    v_peri = np.sqrt(Mu * (2/r1 - 1/a_tr))
    v_apo  = np.sqrt(Mu * (2/r2 - 1/a_tr))

    # Delta-V for each burn
    dv1 = v_peri - v1        # m/s - First burn at perigee (prograde)
    dv2 = v2 - v_apo         # m/s - Second burn at apogee (prograde)

    # Transfer coast time (half period of transfer ellipse)
    T_transfer = np.pi * np.sqrt(a_tr**3 / Mu)   # s

    elements_transfer = {
        "a"            : a_tr,
        "e"            : e_tr,
        "h"            : h_tr,
        "omega_peri"   : 0.0,
        "T"            : T_transfer * 2,
        "r_apoapsis"   : r2,
        "r_periapsis"  : r1,
        "alt_apoapsis" : r2 - Re,
        "alt_periapsis": r1 - Re,
        "v_apoapsis"   : v_apo,
        "v_periapsis"  : v_peri,
        "true_anomaly" : 0.0,
    }

    return {
        "dv1"                : dv1,
        "dv2"                : dv2,
        "dv_total"           : dv1 + dv2,
        "T_transfer"         : T_transfer,
        "alt_parking_km"     : alt_parking / 1000,
        "alt_target_km"      : alt_target / 1000,
        "v_parking_kms"      : v1 / 1000,
        "v_target_kms"       : v2 / 1000,
        "elements_transfer"  : elements_transfer,
    }