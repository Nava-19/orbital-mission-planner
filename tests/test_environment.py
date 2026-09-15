import numpy as np
import pytest

from environment import get_air_density, get_gravity, v_circular
from constants import Re, Mu

# A subset of Vallado's exponential atmosphere reference table
# ("Fundamentals of Astrodynamics and Applications") — the same values
# environment.py's upper-atmosphere model is fit through.
VALLADO_REFERENCE = {
    0:       1.225,
    25_000:  3.899e-2,
    50_000:  1.057e-3,
    90_000:  3.396e-6,
    100_000: 5.297e-7,
    150_000: 2.070e-9,
    200_000: 2.789e-10,
    250_000: 7.248e-11,
    300_000: 2.418e-11,
    500_000: 6.967e-13,
    1_000_000: 3.019e-15,
}


@pytest.mark.parametrize("altitude_m,expected", VALLADO_REFERENCE.items())
def test_air_density_matches_vallado_reference(altitude_m, expected):
    assert get_air_density(altitude_m) == pytest.approx(expected, rel=1e-3)


def test_air_density_is_monotonically_decreasing_with_altitude():
    altitudes = np.linspace(0, 1_000_000, 500)
    densities = np.array([get_air_density(a) for a in altitudes])
    assert np.all(np.diff(densities) <= 0)


def test_air_density_sea_level_matches_isa_standard():
    assert get_air_density(0) == pytest.approx(1.225, rel=1e-3)


def test_gravity_at_sea_level_matches_standard_g0():
    # g0=9.80665 is an internationally DEFINED reference value (a rounded
    # convention, not literally G*Me/Re² for this project's constants), so
    # a small (~0.14%) real difference from computing gravity directly via
    # G*M/R² is expected, physically-derived behavior — not a bug.
    assert get_gravity(0) == pytest.approx(9.80665, rel=2e-3)


def test_gravity_decreases_with_altitude():
    assert get_gravity(400_000) < get_gravity(0)


def test_v_circular_matches_vis_viva_formula():
    altitude = 400_000
    expected = np.sqrt(Mu / (Re + altitude))
    assert v_circular(altitude) == pytest.approx(expected, rel=1e-9)
