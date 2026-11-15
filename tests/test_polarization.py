"""Circular polarisation: E_R / E_L, dBic gains, axial ratio and the sign convention.

The turnstile tests are the check of the sign convention. Time dependence is e^{j omega t}
(as in NEC2), so a source delayed by 90 degrees has phase -90 degrees (voltage -1j). Two
crossed dipoles fed in quadrature radiate towards +z with E ~ x - j*y when y lags x, which is
right-hand circular polarisation in the IEEE sense; the expected results below come from that
theory, not from the program's output.
"""

import json
import math

import numpy as np
import pytest

from antennamax.core.geometry import Feed, Geometry, Wire
from antennamax.results.result import Result
from antennamax.solvers.base import Sweep
from antennamax.solvers.nec2 import Nec2Solver, input_impedance

C = 299_792_458.0
F = 100e6
LAMBDA = C / F
ARM = 0.95 * LAMBDA / 4  # arm length: a bit short of lambda/4 for resonance
SEPARATION = 0.005 * LAMBDA  # the two dipoles cross at this vertical distance, not touching


def turnstile(y_voltage: complex) -> Geometry:
    """Dipole along x (wire 0) and dipole along y (wire 1), fed by two voltage sources."""
    n = 21
    x_dipole = Wire((-ARM, 0, -SEPARATION / 2), (ARM, 0, -SEPARATION / 2), 1e-3, n)
    y_dipole = Wire((0, -ARM, SEPARATION / 2), (0, ARM, SEPARATION / 2), 1e-3, n)
    return Geometry([x_dipole, y_dipole], feeds=[Feed(0, voltage=1.0), Feed(1, voltage=y_voltage)])


def pattern(geometry: Geometry) -> Result:
    return Nec2Solver(pattern_resolution_deg=30).run(geometry, Sweep((F,)))


def db(x):
    return 10 * np.log10(x)


# --- the sign convention, on the turnstile ----------------------------------------------------


def test_y_lagging_by_90_degrees_is_right_hand_circular_towards_plus_z():
    result = pattern(turnstile(-1j))  # y delayed by 90 degrees
    rhcp, lhcp = result.zenith_rhcp_gain_dbic[0], result.zenith_lhcp_gain_dbic[0]
    assert rhcp > lhcp + 20  # RHCP dominates
    assert rhcp == pytest.approx(result.gain_dbi[0, 0, 0], abs=0.2)  # nearly all power is RHCP
    assert result.zenith_axial_ratio_db[0] < 1.0


def test_y_leading_by_90_degrees_is_left_hand_circular_towards_plus_z():
    result = pattern(turnstile(+1j))  # y advanced by 90 degrees
    rhcp, lhcp = result.zenith_rhcp_gain_dbic[0], result.zenith_lhcp_gain_dbic[0]
    assert lhcp > rhcp + 20
    assert lhcp == pytest.approx(result.gain_dbi[0, 0, 0], abs=0.2)
    assert result.zenith_axial_ratio_db[0] < 1.0


def test_the_sense_reverses_towards_minus_z():
    # Seen along -z the same rotation is the opposite hand.
    result = pattern(turnstile(-1j))
    nadir = (0, -1, 0)  # theta = 180 deg is the last row of the theta grid
    assert result.lhcp_gain_dbic[nadir] > result.rhcp_gain_dbic[nadir] + 20


def test_axial_ratio_is_below_1_db_around_the_zenith():
    result = pattern(turnstile(-1j))
    assert np.all(result.axial_ratio_db[0, 0, :] < 1.0)  # theta = 0, every phi column


def test_equal_phase_gives_nearly_linear_polarisation_at_the_zenith():
    # In phase, the two dipoles add up to a +45 degree linear polarisation. They sit 0.005
    # lambda apart vertically, which puts the two components 1.8 degrees out of phase at +z:
    # axial ratio ~ 1 / tan(0.9 degrees) = 64 (36 dB), RHCP and LHCP about 0.27 dB apart.
    result = pattern(turnstile(1.0))
    assert result.zenith_axial_ratio_db[0] > 30
    assert result.zenith_rhcp_gain_dbic[0] == pytest.approx(
        result.zenith_lhcp_gain_dbic[0], abs=0.5
    )


# --- linear dipole -----------------------------------------------------------------------------


def test_linear_dipole_has_equal_rhcp_and_lhcp_and_a_large_axial_ratio():
    geometry = Geometry([Wire((0, -ARM, 0), (0, ARM, 0), 1e-3, 21)])
    result = pattern(geometry)
    zen_r = result.zenith_rhcp_gain_dbic[0]
    assert zen_r == pytest.approx(result.zenith_lhcp_gain_dbic[0], abs=0.1)
    # Same in every direction that has a field: compare the two circular gains.
    right, left = result.rhcp_gain_dbic[0], result.lhcp_gain_dbic[0]
    finite = np.isfinite(right) & np.isfinite(left)
    np.testing.assert_allclose(right[finite], left[finite], atol=0.1)
    ar = result.axial_ratio_db[0]
    assert np.all(ar[finite] > 40)
    # A linear polariser sees half the power in each circular sense: 3 dB below the gain.
    assert zen_r == pytest.approx(result.gain_dbi[0, 0, 0] - 3.01, abs=0.1)


def test_circular_gains_add_up_to_the_total_gain():
    result = pattern(turnstile(-1j))
    total = 10 ** (result.rhcp_gain_dbic / 10) + 10 ** (result.lhcp_gain_dbic / 10)
    expected = 10 ** (result.gain_dbi / 10)
    np.testing.assert_allclose(total, expected, rtol=1e-9, atol=1e-12)


# --- Result formulas on synthetic fields -------------------------------------------------------


def _result_with_fields(e_theta: complex, e_phi: complex, gain: float = 5.0) -> Result:
    shape = (1, 1, 1)
    return Result(
        np.array([1e8]),
        np.array([50 + 0j]),
        theta_rad=np.array([0.0]),
        phi_rad=np.array([0.0]),
        gain_dbi=np.full(shape, gain),
        e_theta=np.full(shape, e_theta),
        e_phi=np.full(shape, e_phi),
    )


def test_formulas_on_synthetic_fields():
    # E = (1, -j): right-handed.  E = (1, +j): left-handed.  E = (1, 0): linear.
    right = _result_with_fields(1.0, -1j)
    assert right.rhcp_gain_dbic[0, 0, 0] == pytest.approx(5.0)
    assert right.lhcp_gain_dbic[0, 0, 0] == -np.inf
    assert abs(right.axial_ratio_db[0, 0, 0]) < 1e-9
    left = _result_with_fields(1.0, +1j)
    assert left.lhcp_gain_dbic[0, 0, 0] == pytest.approx(5.0)
    assert left.rhcp_gain_dbic[0, 0, 0] == -np.inf
    linear = _result_with_fields(1.0, 0.0)
    assert linear.rhcp_gain_dbic[0, 0, 0] == pytest.approx(5.0 - 3.0103, abs=1e-3)
    assert linear.lhcp_gain_dbic[0, 0, 0] == pytest.approx(5.0 - 3.0103, abs=1e-3)
    assert linear.axial_ratio_db[0, 0, 0] == np.inf


def test_elliptical_axial_ratio():
    # E = (1, -0.5j): major axis 1, minor axis 0.5 -> AR = 2 = 6.02 dB.
    result = _result_with_fields(1.0, -0.5j)
    assert result.axial_ratio_db[0, 0, 0] == pytest.approx(20 * math.log10(2), abs=1e-6)


def test_no_field_gives_nan_axial_ratio_and_minus_inf_gains():
    result = _result_with_fields(0.0, 0.0, gain=-np.inf)
    assert np.isnan(result.axial_ratio_db[0, 0, 0])
    assert result.rhcp_gain_dbic[0, 0, 0] == -np.inf


def test_field_arguments_are_validated():
    base = {
        "theta_rad": np.array([0.0]),
        "phi_rad": np.array([0.0]),
        "gain_dbi": np.zeros((1, 1, 1)),
    }
    with pytest.raises(ValueError, match="together"):
        Result(np.array([1e8]), np.array([50 + 0j]), e_theta=np.zeros((1, 1, 1)), **base)
    with pytest.raises(ValueError, match="shape"):
        Result(
            np.array([1e8]),
            np.array([50 + 0j]),
            e_theta=np.zeros((1, 2, 1)),
            e_phi=np.zeros((1, 2, 1)),
            **base,
        )
    with pytest.raises(ValueError, match="far-field components"):
        _ = Result(np.array([1e8]), np.array([50 + 0j])).axial_ratio_db


def test_field_grid_ordering_matches_the_gain_grid():
    # NEC2's flat arrays run theta fastest. Reading them the other way round would break this
    # relation between |E|^2 and the gain (checked here on an asymmetric structure).
    result = pattern(turnstile(-0.5j))
    power = np.abs(result.e_theta) ** 2 + np.abs(result.e_phi) ** 2
    finite = np.isfinite(result.gain_dbi)
    offset = result.gain_dbi[finite] - db(power[finite])
    assert np.ptp(offset) < 1e-6


# --- multiple sources in Geometry --------------------------------------------------------------


def test_single_feed_shorthand_equals_an_explicit_feed():
    wire = Wire((0, -ARM, 0), (0, ARM, 0), 1e-3, 21)
    shorthand = Geometry([wire])
    explicit = Geometry([wire], feeds=[Feed(0, segment=11, voltage=1.0)])
    assert input_impedance(explicit, F) == pytest.approx(input_impedance(shorthand, F))
    # Another amplitude/phase does not change the impedance of a single-source structure.
    scaled = Geometry([wire], feeds=[Feed(0, voltage=2.0 * np.exp(1j * 0.7))])
    assert input_impedance(scaled, F) == pytest.approx(input_impedance(shorthand, F))
    assert shorthand.resolved_feeds() == [Feed(0)]


def test_feeds_take_precedence_over_feed_wire():
    wire = Wire((0, -ARM, 0), (0, ARM, 0), 1e-3, 21)
    other = Wire((0.5, -ARM, 0), (0.5, ARM, 0), 1e-3, 21)
    geometry = Geometry([wire, other], feed_wire=0, feeds=[Feed(1)])
    assert geometry.resolved_feeds() == [Feed(1)]


def test_feed_validation():
    wire = Wire((0, -ARM, 0), (0, ARM, 0), 1e-3, 21)
    with pytest.raises(ValueError, match="out of range"):
        input_impedance(Geometry([wire], feeds=[Feed(3)]), F)
    with pytest.raises(ValueError, match="segment"):
        input_impedance(Geometry([wire], feeds=[Feed(0, segment=22)]), F)
    with pytest.raises(ValueError):
        Feed(0, voltage=0)
    with pytest.raises(ValueError):
        Feed(0, segment=0)
    with pytest.raises(ValueError):
        Feed(-1)
    with pytest.raises(ValueError, match="feed_segment cannot be combined"):
        input_impedance(Geometry([wire], feeds=[Feed(0)]), F, feed_segment=5)


def test_meta_records_the_number_of_sources():
    assert pattern(turnstile(-1j)).meta["n_feeds"] == 2
    single = Nec2Solver().run(Geometry([Wire((0, -ARM, 0), (0, ARM, 0), 1e-3, 21)]), Sweep((F,)))
    assert single.meta["n_feeds"] == 1


# --- impedance of every source -----------------------------------------------------------------


def test_turnstile_gives_one_impedance_per_source():
    result = Nec2Solver().run(turnstile(-1j), Sweep((F, 1.05 * F)))
    assert result.feed_impedances.shape == (2, 2)  # frequencies x sources
    # Column 0 is `impedance`, which also drives the SWR.
    np.testing.assert_allclose(result.feed_impedances[:, 0], result.impedance)
    # The layout is symmetric (the dipoles do not couple, being perpendicular), so both
    # sources see nearly the same impedance.
    z0, z1 = result.feed_impedances[:, 0], result.feed_impedances[:, 1]
    assert np.all(np.abs(z1 - z0) / np.abs(z0) < 0.01)
    gamma = (z0 - result.z0) / (z0 + result.z0)
    np.testing.assert_allclose(result.swr, (1 + np.abs(gamma)) / (1 - np.abs(gamma)))


def _far_apart_dipoles(order: tuple[int, int]) -> Geometry:
    """A half-wave-ish and a short dipole, 50 m apart so that coupling is negligible."""
    long = Wire((0, -ARM, 0), (0, ARM, 0), 1e-3, 21)
    short = Wire((50.0, -0.3 * ARM, 0), (50.0, 0.3 * ARM, 0), 1e-3, 21)
    return Geometry([long, short], feeds=[Feed(w) for w in order])


def test_feed_impedances_follow_the_order_of_the_sources():
    z_long = input_impedance(Geometry([Wire((0, -ARM, 0), (0, ARM, 0), 1e-3, 21)]), F)
    z_short = input_impedance(Geometry([Wire((0, -0.3 * ARM, 0), (0, 0.3 * ARM, 0), 1e-3, 21)]), F)
    assert abs(z_long - z_short) > 100  # the two are clearly different
    forward = Nec2Solver().run(_far_apart_dipoles((0, 1)), Sweep((F,)))
    reverse = Nec2Solver().run(_far_apart_dipoles((1, 0)), Sweep((F,)))
    assert forward.feed_impedances[0] == pytest.approx([z_long, z_short], rel=0.02)
    assert reverse.feed_impedances[0] == pytest.approx([z_short, z_long], rel=0.02)
    # `impedance` (and SWR) always refer to the first source in the list.
    assert forward.impedance[0] == pytest.approx(z_long, rel=0.02)
    assert reverse.impedance[0] == pytest.approx(z_short, rel=0.02)


def test_single_source_has_a_single_column():
    result = Nec2Solver().run(Geometry([Wire((0, -ARM, 0), (0, ARM, 0), 1e-3, 21)]), Sweep((F,)))
    assert result.feed_impedances.shape == (1, 1)
    manual = Result(np.array([1e8, 2e8]), np.array([50 + 0j, 60 + 0j]))
    assert manual.feed_impedances.shape == (2, 1)  # defaults to the first-source column


def test_feed_impedances_shape_is_validated():
    with pytest.raises(ValueError, match="feed_impedances"):
        Result(np.array([1e8]), np.array([50 + 0j]), feed_impedances=np.zeros((2, 2)))


def test_json_contains_feed_impedances():
    result = Nec2Solver().run(turnstile(-1j), Sweep((F,)))
    data = result.to_dict()
    assert np.shape(data["feed_impedances_real"]) == (1, 2)
    assert np.shape(data["feed_impedances_imag"]) == (1, 2)
    assert data["feed_impedances_real"][0][0] == pytest.approx(result.impedance[0].real)


def test_cli_notes_that_z_and_swr_are_for_the_first_source(monkeypatch, capsys):
    from antennamax.cli import main as cli
    from antennamax.io.design import LoadedDesign
    from antennamax.templates.base import Template

    class TurnstileTemplate(Template):
        def to_geometry(self) -> Geometry:
            return turnstile(-1j)

    design = LoadedDesign("turnstile", TurnstileTemplate(), Sweep((F,)), None)
    monkeypatch.setattr(cli, "load_design", lambda path: design)
    assert cli.main(["run", "unused.yaml"]) == 0
    out = capsys.readouterr().out
    assert "Note: 2 sources; Z and SWR are those of the first source" in out
    assert cli.main(["run", "unused.yaml", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert np.shape(result["feed_impedances_real"]) == (1, 2)


def test_cli_has_no_note_for_a_single_source(capsys):
    from antennamax.cli.main import main

    assert main(["run", "examples/dipole_145mhz.yaml"]) == 0
    assert "Note:" not in capsys.readouterr().out
