import numpy as np
from scipy.interpolate import PchipInterpolator
from constants import G, Me, Re, Tsl, Lmb, Psl, Rair, Htr, Mu

def get_gravity(altitude):
    # Returns gravitational acceleration at a given altitude
    return (G * Me) / (altitude + Re)**2

# Exponential atmosphere reference table (base altitude in m, reference
# density in kg/m^3, scale height in m), from Vallado's "Fundamentals of
# Astrodynamics and Applications" — the standard simplified model used for
# satellite drag/decay estimation, covering the stratosphere through the
# exosphere. These are the reference (altitude, density) NODES; how they're
# turned into a continuous curve between nodes is handled below.
_EXP_ATMOSPHERE = [
    (25000,   3.899e-02, 6349),
    (30000,   1.774e-02, 6682),
    (40000,   3.972e-03, 7554),
    (50000,   1.057e-03, 8382),
    (60000,   3.206e-04, 7714),
    (70000,   8.770e-05, 6549),
    (80000,   1.905e-05, 5799),
    (90000,   3.396e-06, 5382),
    (100000,  5.297e-07, 5877),
    (110000,  9.661e-08, 7263),
    (120000,  2.438e-08, 9473),
    (130000,  8.484e-09, 12636),
    (140000,  3.845e-09, 16149),
    (150000,  2.070e-09, 22523),
    (180000,  5.464e-10, 29740),
    (200000,  2.789e-10, 37105),
    (250000,  7.248e-11, 45546),
    (300000,  2.418e-11, 53628),
    (350000,  9.518e-12, 53298),
    (400000,  3.725e-12, 58515),
    (450000,  1.585e-12, 60828),
    (500000,  6.967e-13, 63822),
    (600000,  1.454e-13, 71835),
    (700000,  3.614e-14, 88667),
    (800000,  1.170e-14, 124640),
    (900000,  5.245e-15, 181050),
    (1000000, 3.019e-15, 268000),
]

# Using each row's OWN scale height as a pure exponential up to the next
# row reproduces every reference value exactly (each row was fit so the
# next one falls out of its formula) — but it means the LOCAL scale height
# (the slope of ln(density) vs altitude) jumps abruptly at every node, by
# as much as 30-40% in the 100-300km range, even though the density value
# itself stays continuous there. Real atmospheric scale height changes
# smoothly with altitude (it depends on temperature and mean molecular
# mass, which don't jump), so a piecewise-exponential-per-row curve has
# visible "kinks" a truly smooth model wouldn't have.
#
# A monotonic cubic (PCHIP) fit through ln(density) vs altitude passes
# through every one of the same reference nodes EXACTLY, while keeping the
# curve's slope continuous in between — removing the artificial kinks
# without inventing or altering a single reference value.
_TABLE_ALT = np.array([h for h, _, _ in _EXP_ATMOSPHERE], dtype=float)
_TABLE_LOGRHO = np.array([np.log(rho) for _, rho, _ in _EXP_ATMOSPHERE])
_LOG_RHO_INTERP = PchipInterpolator(_TABLE_ALT, _TABLE_LOGRHO, extrapolate=True)

def get_air_density(altitude):
    # Returns air density (kg/m³). The troposphere/lower stratosphere (up
    # to 20km) use a physically-derived ISA polytropic model (temperature
    # lapse rate + hydrostatic pressure) — more precise here than a table
    # lookup would be, since temperature actually varies with altitude in
    # this range, including a genuine slope change at the tropopause
    # (11km) that's real physics, not an artifact. From 20km up through
    # 1000km, a smooth fit through the standard reference exponential
    # atmosphere table takes over (see _EXP_ATMOSPHERE above).
    if altitude < Htr:          # Troposphere
        T = Tsl - Lmb * altitude
        p = Psl * (T / Tsl) ** 5.2561
        return p / (Rair * T)   # Ideal gas law: ρ = p / (R_air * T)
    elif altitude < 20000:      # Lower stratosphere
        T = Tsl - Lmb * Htr    # Temperature constant above tropopause
        p = Psl * (T / Tsl) ** 5.2561 * np.exp(-0.0001577 * (altitude - Htr))
        return p / (Rair * T)

    alt_clamped = min(altitude, _TABLE_ALT[-1])
    return float(np.exp(_LOG_RHO_INTERP(alt_clamped)))

def v_circular(altitude):
    """Returns circular orbital velocity (m/s) at a given altitude above surface"""
    return np.sqrt(Mu / (Re + altitude))