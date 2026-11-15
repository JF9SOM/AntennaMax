import numpy as np
import pytest

from antennamax.core.geometry import Geometry, Wire
from antennamax.core.units import mhz_to_hz
from antennamax.results.result import Result
from antennamax.solvers.base import Solver, Sweep
from antennamax.solvers.nec2 import Nec2Solver, _nec_gain_to_dbi

C = 299_792_458.0
F = mhz_to_hz(100.0)


def _dipole(radius: float = 1e-3, segments: int = 31) -> Geometry:
    half = C / F / 4  # lambda/2 total, along z
    return Geometry([Wire((0, 0, -half), (0, 0, half), radius, segments)])


def test_nec2solver_satisfies_protocol():
    assert isinstance(Nec2Solver(), Solver)
    assert Nec2Solver().supports(_dipole())
    assert not Nec2Solver().supports(Geometry())


def test_dipole_max_gain():
    result = Nec2Solver(pattern_resolution_deg=10).run(_dipole(), Sweep((F,)))
    # A lossless lambda/2 dipole has directivity 1.64 = 2.15 dBi (Balanis, Antenna Theory).
    # With no loss in NEC2 (perfect conductor) gain equals directivity; the finite-radius
    # current distribution and the 10 deg grid shift it by a few hundredths of a dB
    # (PyNEC gives 2.17 dBi), so +/-0.1 dB is allowed.
    assert result.gain_dbi is not None
    assert result.gain_dbi.max() == pytest.approx(2.15, abs=0.1)


def test_pattern_null_on_wire_axis():
    result = Nec2Solver(pattern_resolution_deg=10).run(_dipole(), Sweep((F,)))
    gain = result.gain_dbi[0]  # (theta, phi)
    peak = gain.max()
    # The wire lies along z, i.e. theta = 0 and 180 deg: the dipole has nulls there.
    assert np.all(gain[0, :] < peak - 30)
    assert np.all(gain[-1, :] < peak - 30)
    # Maximum is broadside (theta = 90 deg) and omnidirectional in phi.
    assert np.argmax(gain.max(axis=1)) == len(result.theta_rad) // 2
    assert np.ptp(gain[len(result.theta_rad) // 2]) < 0.1


def test_sweep_array_lengths():
    freqs = tuple(mhz_to_hz(f) for f in (90.0, 100.0, 110.0))
    result = Nec2Solver(pattern_resolution_deg=30).run(_dipole(), Sweep(freqs))
    assert isinstance(result, Result)
    assert result.frequencies_hz.shape == (3,)
    assert result.impedance.shape == (3,)
    assert result.swr.shape == (3,)
    assert result.theta_rad.shape == (7,)
    assert result.phi_rad.shape == (12,)
    assert result.gain_dbi.shape == (3, 7, 12)
    # Reactance rises with frequency around resonance.
    assert np.all(np.diff(result.impedance.imag) > 0)


def test_no_pattern_by_default():
    result = Nec2Solver().run(_dipole(), Sweep((F,)))
    assert result.gain_dbi is None and result.theta_rad is None and result.phi_rad is None


def test_swr():
    r = Result(np.array([1e8, 1e8]), np.array([50 + 0j, 100 + 0j]))
    assert r.swr == pytest.approx([1.0, 2.0])
    # Short circuit and purely reactive loads reflect everything.
    assert Result(np.array([1e8]), np.array([0j])).swr[0] == np.inf
    assert Result(np.array([1e8]), np.array([1j * 30])).swr[0] == np.inf
    assert Result(np.array([1e8]), np.array([50 + 1j * 1e-3])).swr[0] == pytest.approx(
        1.0, abs=1e-3
    )


def test_invalid_resolution():
    with pytest.raises(ValueError):
        Nec2Solver(pattern_resolution_deg=7)


def test_nec_null_marker_converted_to_minus_inf():
    converted = _nec_gain_to_dbi(np.array([-999.99, -40.0, 2.15]))
    assert converted[0] == -np.inf
    assert converted[1:] == pytest.approx([-40.0, 2.15])

    result = Nec2Solver(pattern_resolution_deg=10).run(_dipole(), Sweep((F,)))
    assert np.isneginf(result.gain_dbi[0, 0, :]).all()  # null on the wire axis
    assert not np.any(result.gain_dbi == -999.99)
    assert not np.any(np.isnan(result.gain_dbi))
