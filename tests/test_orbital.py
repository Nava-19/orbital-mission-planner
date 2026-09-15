import numpy as np
import pytest

from orbital import (
    compute_orbital_elements,
    hohmann_transfer,
    get_moon_position,
    get_moon_velocity,
    set_moon_phase,
)
from constants import Re, Mu, MoonOrbitR, MoonPeriod


def test_circular_orbit_has_zero_eccentricity():
    altitude = 400_000
    r = Re + altitude
    v = np.sqrt(Mu / r)
    el = compute_orbital_elements(r, 0, 0, v)
    assert el["e"] == pytest.approx(0.0, abs=1e-9)
    assert el["alt_apoapsis"] == pytest.approx(altitude, rel=1e-6)
    assert el["alt_periapsis"] == pytest.approx(altitude, rel=1e-6)


def test_circular_orbit_period_matches_keplers_third_law():
    altitude = 400_000
    r = Re + altitude
    v = np.sqrt(Mu / r)
    el = compute_orbital_elements(r, 0, 0, v)
    expected_T = 2 * np.pi * np.sqrt(r**3 / Mu)
    assert el["T"] == pytest.approx(expected_T, rel=1e-6)


def test_hohmann_transfer_leo_to_geo_matches_published_value():
    # Classic 300km LEO -> GEO Hohmann transfer — total Δv is a widely
    # published textbook value (e.g. Curtis, "Orbital Mechanics for
    # Engineering Students"), used here as an independent sanity check.
    result = hohmann_transfer(300_000, 35_786_000)
    assert result["dv_total"] == pytest.approx(3935, rel=0.02)


def test_hohmann_transfer_dv1_matches_direct_vis_viva_calc():
    alt1, alt2 = 400_000, 20_000_000
    result = hohmann_transfer(alt1, alt2)
    r1, r2 = Re + alt1, Re + alt2
    a_tr = (r1 + r2) / 2
    v1 = np.sqrt(Mu / r1)
    v_peri = np.sqrt(Mu * (2 / r1 - 1 / a_tr))
    assert result["dv1"] == pytest.approx(v_peri - v1, rel=1e-9)


def test_moon_orbit_stays_at_constant_radius():
    set_moon_phase(0.0)
    for t in np.linspace(0, MoonPeriod, 20):
        r = np.hypot(*get_moon_position(t))
        assert r == pytest.approx(MoonOrbitR, rel=1e-9)


def test_moon_completes_one_orbit_per_moon_period():
    set_moon_phase(0.0)
    x0, y0 = get_moon_position(0.0)
    xT, yT = get_moon_position(MoonPeriod)
    assert x0 == pytest.approx(xT, abs=1.0)
    assert y0 == pytest.approx(yT, abs=1.0)


def test_moon_velocity_is_purely_tangential():
    # For a circular orbit, velocity should have zero radial component.
    set_moon_phase(0.3)
    t = 12345.0
    x, y = get_moon_position(t)
    vx, vy = get_moon_velocity(t)
    radial_component = (x * vx + y * vy) / np.hypot(x, y)
    assert radial_component == pytest.approx(0.0, abs=1e-6)
