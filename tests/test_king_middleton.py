"""Compare NEC2 (PyNEC) dipole impedances with King-Middleton second-order values.

Reference data and its provenance: tests/reference/king_middleton.csv (secondary source,
not yet checked against King, The Theory of Linear Antennas, 1956).

Tolerances were fixed BEFORE looking at any result and must not be widened to make a case
pass: R within +/-5 %, X within +/-5 ohm. Segment counts follow segments_for() (Delta/a >= 8).
Cases that miss are listed in KNOWN_FAILURES and run as
xfail(strict=True) with the observed difference recorded; see docs/VERIFICATION.md.
"""

import csv
import math
import warnings
from pathlib import Path

import pytest

from antennamax.solvers.nec2 import input_impedance
from antennamax.solvers.thin_wire import ThinWireWarning
from antennamax.templates import Dipole

C = 299_792_458.0
WAVELENGTH = 1.0  # m
FREQUENCY_HZ = C / WAVELENGTH
MAX_SEGMENTS = 101
MIN_SEGMENT_TO_RADIUS = 8.0  # NEC2 guideline for the standard kernel: segment length / radius > 8

R_REL_TOL = 0.05
X_ABS_TOL = 5.0

# (omega, beta_h) -> reason. Filled in only from observed differences.
KNOWN_FAILURES: dict[tuple[float, float], str] = {
    # Observed with PyNEC 2.4.0, N = 63 (Delta/a = 8.22): R is within tolerance (+4.77 %), X is not.
    (
        12.5,
        1.6,
    ): "X: NEC2 66.932 vs K-M 60.400 ohm (dX +6.53 ohm > 5 ohm); R: 91.837 vs 87.655 (+4.77 %)",
}


def _load_reference() -> list[tuple[float, float, float, float]]:
    path = Path(__file__).resolve().parent / "reference" / "king_middleton.csv"
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    rows = csv.DictReader(lines)
    return [
        (float(r["omega"]), float(r["beta_h"]), float(r["R_ohm"]), float(r["X_ohm"])) for r in rows
    ]


def segment_to_radius(omega: float, segments: int) -> float:
    """Delta/a here: Delta = 2h/N, a = 2h exp(-omega/2), so Delta/a = e^(omega/2) / N."""
    return math.exp(omega / 2) / segments


def segments_for(omega: float) -> int:
    """Segment rule, fixed before looking at any result.

    The largest odd N (centre feed) with Delta/a >= 8, capped at 101:
    omega 12.5 -> N = 63 (Delta/a = 8.22); omega 15 -> N = 101 (cap; Delta/a = 17.9);
    omega 20 -> N = 101 (cap; Delta/a = 218).
    """
    n = min(MAX_SEGMENTS, math.floor(math.exp(omega / 2) / MIN_SEGMENT_TO_RADIUS))
    return n if n % 2 == 1 else n - 1


def nec2_impedance(omega: float, beta_h: float, segments: int | None = None) -> complex:
    """Centre-fed dipole with half-length h = beta_h / k and radius a = 2h exp(-omega / 2).

    `segments` defaults to segments_for(omega).
    """
    if segments is None:
        segments = segments_for(omega)
    k = 2 * math.pi / WAVELENGTH
    h = beta_h / k
    a = 2 * h * math.exp(-omega / 2)
    dipole = Dipole(
        center_frequency_hz=FREQUENCY_HZ, length_m=2 * h, diameter_m=2 * a, segments=segments
    )
    # The segment rule keeps delta/a >= 8, so the solver's thin-wire check must stay silent.
    with warnings.catch_warnings():
        warnings.simplefilter("error", ThinWireWarning)
        return input_impedance(dipole.to_geometry(), FREQUENCY_HZ)


def _param(row):
    omega, beta_h, _, _ = row
    marks = []
    if (omega, beta_h) in KNOWN_FAILURES:
        marks.append(pytest.mark.xfail(strict=True, reason=KNOWN_FAILURES[(omega, beta_h)]))
    return pytest.param(*row, marks=marks, id=f"omega{omega:g}-bh{beta_h:g}")


@pytest.mark.parametrize(
    ("omega", "beta_h", "r_ref", "x_ref"), [_param(r) for r in _load_reference()]
)
def test_matches_king_middleton(omega, beta_h, r_ref, x_ref):
    z = nec2_impedance(omega, beta_h)
    assert z.real == pytest.approx(r_ref, rel=R_REL_TOL), f"R: NEC2 {z.real:.3f} vs K-M {r_ref}"
    assert z.imag == pytest.approx(x_ref, abs=X_ABS_TOL), f"X: NEC2 {z.imag:.3f} vs K-M {x_ref}"
