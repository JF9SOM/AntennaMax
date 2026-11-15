import math

import numpy as np
import pytest
from pydantic import ValidationError

from antennamax.core.geometry import Geometry, Wire
from antennamax.core.units import mhz_to_hz
from antennamax.results.result import Result
from antennamax.solvers.base import Sweep
from antennamax.solvers.nec2 import Nec2Solver, input_impedance
from antennamax.templates import Dipole, Yagi

C = 299_792_458.0


def _yagi_params(**overrides):
    # PROVISIONAL dimensions (not from a published design): a generic 3-element 144 MHz
    # beam with reflector 1030 mm, driven element 980 mm, director 920 mm, 6 mm tubing,
    # spaced 300 mm (~0.14 lambda) apart. Only the qualitative behaviour is tested.
    params = {
        "center_frequency_mhz": 144.0,
        "feed_index": 1,
        "elements": [
            {"position_mm": 0, "length_mm": 1030, "diameter_mm": 6},
            {"position_mm": 300, "length_mm": 980, "diameter_mm": 6},
            {"position_mm": 600, "length_mm": 920, "diameter_mm": 6},
        ],
    }
    params.update(overrides)
    return params


# --- Unit handling -----------------------------------------------------------------------


def test_unit_suffixes_are_converted_to_si():
    d = Dipole(center_frequency_mhz=144.0, length_mm=1000, diameter_mm=5)
    assert d.center_frequency_hz == pytest.approx(144e6)
    assert d.length_m == pytest.approx(1.0)
    assert d.diameter_m == pytest.approx(0.005)
    assert Dipole(center_frequency_hz=144e6, length_m=1.0, diameter_m=0.005) == d


def test_same_quantity_in_two_units_is_rejected():
    with pytest.raises(ValidationError):
        Dipole(center_frequency_mhz=144.0, center_frequency_hz=144e6, diameter_mm=5)


def test_default_length_is_resonance_estimate():
    d = Dipole(center_frequency_mhz=100.0, diameter_mm=2)
    assert d.resolved_length_m == pytest.approx(0.95 * C / 100e6 / 2)


# --- Dipole ------------------------------------------------------------------------------


def test_dipole_template_matches_hand_written_dipole():
    f = mhz_to_hz(100.0)
    half = C / f / 4
    by_hand = Geometry([Wire((0, 0, -half), (0, 0, half), 1e-3, 31)])
    template = Dipole(center_frequency_hz=f, length_m=2 * half, diameter_m=2e-3, segments=31)
    # Free space is rotation invariant, so the axis (z by hand, y in the template) is irrelevant.
    assert input_impedance(template.to_geometry(), f) == pytest.approx(
        input_impedance(by_hand, f), rel=1e-6
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"length_mm": -100},
        {"length_mm": 0},
        {"diameter_mm": -1},
        {"center_frequency_mhz": 0},
        {"segments": 30},  # even: no centre segment
        {"segments": -1},
        {"length_mm": 3, "diameter_mm": 5},  # not a thin wire
        {"unknown_field": 1},
    ],
)
def test_dipole_invalid_parameters(kwargs):
    params = {"center_frequency_mhz": 144.0, "length_mm": 1000, "diameter_mm": 5}
    params.update(kwargs)
    with pytest.raises(ValidationError):
        Dipole(**params)


# --- Yagi --------------------------------------------------------------------------------


def test_yagi_segments_are_shared_and_odd():
    y = Yagi(**_yagi_params())
    geom = y.to_geometry()
    counts = {w.segments for w in geom.wires}
    assert counts == {y.segments}
    assert y.segments % 2 == 1
    assert geom.feed_wire == 1
    # Longer elements (finer wavelength fraction) never get fewer segments.
    finer = Yagi(**_yagi_params(segments_per_wavelength=40))
    assert finer.segments > y.segments


def test_yagi_beam_points_to_director_side():
    solver = Nec2Solver(pattern_resolution_deg=5)
    f = mhz_to_hz(144.0)
    yagi = solver.run(Yagi(**_yagi_params()).to_geometry(), Sweep((f,)))
    dipole = solver.run(Dipole(center_frequency_hz=f, diameter_mm=6).to_geometry(), Sweep((f,)))

    assert yagi.max_gain_dbi[0] > dipole.max_gain_dbi[0] + 3.0
    assert yagi.front_to_back_db[0] > 3.0  # positive, and clearly more than numerical noise
    theta, phi = yagi.max_gain_direction_rad[0]
    # Boom along x, directors at larger x: beam towards +x (theta = 90 deg, phi = 0).
    assert theta == pytest.approx(math.pi / 2, abs=math.radians(10))
    assert math.cos(phi) > math.cos(math.radians(10))
    assert np.isfinite(yagi.impedance).all()


@pytest.mark.parametrize(
    "overrides",
    [
        {"feed_index": 3},  # out of range
        {"feed_index": -1},
        {"elements": _yagi_params()["elements"][:1]},  # a single element
        {
            "elements": [
                {"position_mm": 0, "length_mm": -1030, "diameter_mm": 6},
                {"position_mm": 300, "length_mm": 980, "diameter_mm": 6},
            ]
        },
        {
            "elements": [  # duplicate positions
                {"position_mm": 0, "length_mm": 1030, "diameter_mm": 6},
                {"position_mm": 0, "length_mm": 980, "diameter_mm": 6},
            ]
        },
        {"segments_per_wavelength": 0},
        {"center_frequency_mhz": -144.0},
    ],
)
def test_yagi_invalid_parameters(overrides):
    with pytest.raises(ValidationError):
        Yagi(**_yagi_params(**overrides))


# --- Result: front-to-back ---------------------------------------------------------------


def test_front_to_back_on_synthetic_pattern():
    theta = np.radians(np.arange(0, 181, 90.0))  # 0, 90, 180
    phi = np.radians(np.arange(0, 360, 90.0))  # 0, 90, 180, 270
    gain = np.full((1, 3, 4), -10.0)
    gain[0, 1, 0] = 8.0  # peak at theta = 90, phi = 0
    gain[0, 1, 2] = 3.0  # opposite direction
    r = Result(np.array([1e8]), np.array([50 + 0j]), theta_rad=theta, phi_rad=phi, gain_dbi=gain)
    assert r.front_to_back_db == pytest.approx([5.0])
    assert r.max_gain_dbi == pytest.approx([8.0])
    gain[0, 1, 2] = -np.inf
    r = Result(np.array([1e8]), np.array([50 + 0j]), theta_rad=theta, phi_rad=phi, gain_dbi=gain)
    assert r.front_to_back_db[0] == np.inf


def test_front_to_back_requires_pattern():
    r = Result(np.array([1e8]), np.array([50 + 0j]))
    with pytest.raises(ValueError):
        _ = r.front_to_back_db
