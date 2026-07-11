import numpy as np
from constants import G, Me, Re, Tsl, Lmb, Psl, Rair, Htr, Mu

def get_gravity(altitude):
    # Returns gravitational acceleration at a given altitude
    return (G * Me) / (altitude + Re)**2

def get_air_density(altitude):
    # Returns air density (kg/m³) using a simplified ISA model.
    # Valid for altitudes up to ~32km.
    if altitude < Htr:          # Troposphere
        T = Tsl - Lmb * altitude
        p = Psl * (T / Tsl) ** 5.2561
    elif altitude < 20000:      # Lower stratosphere
        T = Tsl - Lmb * Htr    # Temperature constant above tropopause
        p = Psl * (T / Tsl) ** 5.2561 * np.exp(-0.0001577 * (altitude - Htr))
    else:                       # Upper stratosphere
        T = (Tsl - Lmb * Htr) + 0.001 * (altitude - 20000)
        p = 5474 * (T / 216.65) ** -34.16

    return p / (Rair * T)       # Ideal gas law: ρ = p / (R_air * T)

def v_circular(altitude):
    """Returns circular orbital velocity (m/s) at a given altitude above surface"""
    return np.sqrt(Mu / (Re + altitude))