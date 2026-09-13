# --- Earth ---
Me = 5.9722e24      # Kg       - Earth's mass
G  = 6.67430e-11    # N·m²/Kg² - Universal gravitational constant
Re = 6.371e6        # m        - Earth's mean radius
g0 = 9.80665        # m/s²     - Standard gravity at sea level (ISA)

# --- Earth Rotation ---
omega = 7.2921150e-5   # rad/s - Earth's angular velocity
v_rot = omega * Re     # m/s   - Surface rotational velocity at equator (~465 m/s)

# --- Atmosphere (ISA Model) ---
Psl  = 101325       # Pa       - Sea level pressure
Tsl  = 288.15       # K        - Sea level temperature
Lmb  = 0.0065       # K/m      - Tropospheric temperature lapse rate
Rair = 287.05       # J/kg·K   - Specific gas constant (dry air)
Htr  = 11000        # m        - Tropopause altitude

# --- Orbital ---
Mu   = 3.986004418e14  # m³/s² - Standard gravitational parameter (G*Me)
Vsoi = 11186           # m/s   - Earth's escape velocity

# --- Moon (simplified circular orbit — see orbital.get_moon_position) ---
Mmoon      = 7.342e22        # kg    - Moon's mass
MuMoon     = G * Mmoon       # m³/s² - Moon's standard gravitational parameter (~4.9048e12)
MoonOrbitR = 384400e3        # m     - Moon's mean orbital radius (semi-major axis)
MoonPeriod = 27.321661 * 86400  # s  - Moon's sidereal orbital period (~27.32 days)