import numpy as np
import pytest

from solver import run_coast, run_reentry
from constants import Re, Mu


def test_run_coast_conserves_specific_orbital_energy():
    altitude = 400_000
    r = Re + altitude
    v = np.sqrt(Mu / r) * 1.2   # slightly elliptical, not circular
    state0 = [r, 0, 0, v]
    _, y = run_coast(state0, 0, 3600)
    energy0 = 0.5 * v**2 - Mu / r
    r_final = np.hypot(y[0][-1], y[1][-1])
    v_final = np.hypot(y[2][-1], y[3][-1])
    energy_final = 0.5 * v_final**2 - Mu / r_final
    # RK45's default adaptive tolerances leave a small (~1e-5 relative)
    # numerical drift over this window — real, expected integrator error,
    # not a physics bug.
    assert energy_final == pytest.approx(energy0, rel=1e-4)


def test_run_coast_conserves_specific_angular_momentum():
    altitude = 500_000
    r = Re + altitude
    v = np.sqrt(Mu / r) * 0.9
    state0 = [r, 0, 0, v]
    _, y = run_coast(state0, 0, 5000)
    h0 = r * v
    h_final = y[0][-1] * y[3][-1] - y[1][-1] * y[2][-1]
    # Same adaptive-integrator numerical drift as the energy conservation
    # test above.
    assert h_final == pytest.approx(h0, rel=1e-4)


def test_run_reentry_impacts_the_surface_for_a_steep_deorbit():
    altitude = 200_000
    r = Re + altitude
    v_circ = np.sqrt(Mu / r)
    # A retrograde burn dropping periapsis well below the surface
    state0 = [r, 0, 0, v_circ * 0.85]
    _, y, impacted = run_reentry(state0, 0, 6000, mass=1000, Cd=1.2, A=5.0)
    assert impacted is True
    r_final = np.hypot(y[0][-1], y[1][-1])
    assert r_final == pytest.approx(Re, abs=1000)


def test_run_reentry_does_not_impact_a_stable_circular_orbit():
    altitude = 400_000
    r = Re + altitude
    v_circ = np.sqrt(Mu / r)
    state0 = [r, 0, 0, v_circ]
    _, _, impacted = run_reentry(state0, 0, 3000, mass=1000, Cd=1.2, A=5.0)
    assert impacted is False
