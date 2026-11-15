import math

from scipy.optimize import brentq

from antennamax.core.geometry import Geometry, Wire
from antennamax.core.units import mhz_to_hz
from antennamax.solvers.nec2 import input_impedance

C = 299_792_458.0
F = mhz_to_hz(100.0)
WAVELENGTH = C / F


def _dipole_impedance(length_in_wavelengths: float, radius: float, segments: int = 31) -> complex:
    half = length_in_wavelengths * WAVELENGTH / 2
    geom = Geometry([Wire((0, 0, -half), (0, 0, half), radius, segments)])
    return input_impedance(geom, F)


def _resonant_length(radius: float) -> float:
    """Dipole length (in wavelengths) at which the input reactance is zero."""
    return brentq(lambda length: _dipole_impedance(length, radius).imag, 0.40, 0.50, xtol=1e-5)


# --- Physical validity tests -------------------------------------------------------------


def test_resonant_length_is_slightly_shorter_than_half_wave():
    # A thin-wire dipole resonates (X = 0) somewhat below 0.5 lambda (end effect);
    # the usual rule of thumb is about 0.47-0.495 lambda depending on thickness.
    assert 0.47 <= _resonant_length(1e-3) <= 0.495


def test_resonant_length_decreases_with_radius():
    # A thicker conductor lowers the Q and shortens the resonant length.
    lengths = [_resonant_length(a) for a in (1e-4, 1e-3, 5e-3)]
    assert lengths[0] > lengths[1] > lengths[2]


# --- Regression test ---------------------------------------------------------------------


def test_half_wave_dipole_regression():
    # Regression value computed with PyNEC 2.4.0 (100 MHz, lambda/2, radius 1 mm, 31 segments).
    # Not yet cross-checked against an independent engine (nec2c / MMANA).
    # Note it differs from the textbook 73.1 + j42.5 ohm (induced-EMF method, sinusoidal
    # current); see docs/VERIFICATION.md.
    # PyNEC 2.4.0 による計算値。独立エンジン(nec2c/MMANA)との照合は未実施。
    z = _dipole_impedance(0.5, 1e-3)
    assert math.isclose(z.real, 81.92, abs_tol=0.5)
    assert math.isclose(z.imag, 46.54, abs_tol=0.5)
