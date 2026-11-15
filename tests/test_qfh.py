"""QFH template: dimensions (Coppens / KF8EEZ formulas) and NEC2 behaviour.

The acceptance criteria of the NEC2 checks were fixed before the first run and must not be
loosened to make a case pass: zenith axial ratio < 3 dB at 137.5 and 435 MHz, and the dominant
circular sense at the zenith reverses with the winding.

The first version failed the axial-ratio criterion (7.62 / 12.49 dB). Its beam and good circular
polarisation pointed straight down, which showed that the small loop's feed polarity was
reversed; the wiring was corrected (Qfh.to_geometry), the criteria were not touched. See
docs/VERIFICATION.md.

Winding and polarisation (feed at the top, towards +z): right winding -> LHCP, left winding ->
RHCP. Expected values from the literature, not from the program's output:
  AN-SOF, https://antennasimulator.com/index.php/2022/11/22/qfh-antenna-for-noaa-satellite-reception/
    (left-handed helices give RHCP; backfire configuration with the feed point at the top);
  AMSAT-BB, https://mailman.amsat.org/hyperkitty/list/amsat-bb@amsat.org/thread/LP3UGHL23MQEGJK57YOLFTRLC2BFH6RJ
    (cited as given by the project owner; the page could not be retrieved).
"""

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from antennamax.core.segmentation import choose_segments
from antennamax.io.design import load_design
from antennamax.solvers.base import Sweep
from antennamax.solvers.nec2 import Nec2Solver
from antennamax.templates.qfh import COPPENS_SPEED_OF_LIGHT, Qfh, wire_correction_factor

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def coppens(**overrides) -> Qfh:
    """The reference case of the dimension tests, with the original calculator's c = 3e8."""
    params = {
        "center_frequency_mhz": 137.5,
        "diameter_mm": 3,
        "bend_radius_mm": 15,
        "width_height_ratio": 0.44,
        "speed_of_light_m_s": COPPENS_SPEED_OF_LIGHT,
    }
    params.update(overrides)
    return Qfh(**params)


# --- dimensions -----------------------------------------------------------------------------


def test_wavelength_compensated_wavelength_and_bend_correction():
    dims = coppens().dimensions
    assert dims.wavelength_m == pytest.approx(3e8 / 137.5e6)  # 2.181818 m
    assert dims.wavelength_m == pytest.approx(2.181818, abs=1e-6)
    # delta(3 mm) = 1.064 (table entry), so lambda_c = 2.181818 * 1.064 = 2.321454 m.
    assert wire_correction_factor(0.003) == pytest.approx(1.064)
    assert dims.compensated_wavelength_m == pytest.approx(2.181818181818 * 1.064)
    assert dims.compensated_wavelength_m == pytest.approx(2.321454, abs=1e-6)
    # bcorr = 2R - pi R / 2 = 30 - 23.5619 = 6.438055 mm for R = 15 mm
    assert dims.bend_correction_m * 1000 == pytest.approx(6.438055, abs=1e-6)


def test_loop_dimensions_follow_the_formulas():
    q = coppens(turns=1.0)  # N = 1 as in the formula page's example
    dims = q.dimensions
    lam_c = 2.181818181818 * 1.064
    bcorr = 2 * 0.015 - math.pi * 0.015 / 2
    ratio, turns = 0.44, 1.0
    for loop, factor in ((dims.large, 1.026), (dims.small, 0.975)):
        total = factor * lam_c
        compensated = total + 4 * bcorr
        d = 0.5 * compensated / (1 + math.sqrt(1 / ratio**2 + (turns * math.pi) ** 2))
        v = (compensated - 2 * d) / 2
        assert loop.total_length_m == pytest.approx(total)
        assert loop.compensated_length_m == pytest.approx(compensated)
        assert loop.horizontal_m == pytest.approx(d)
        assert loop.compensated_horizontal_m == pytest.approx(d - 0.030)
        assert loop.vertical_m == pytest.approx(v)
        assert loop.compensated_vertical_m == pytest.approx(v - 0.030)
        assert loop.height_m == pytest.approx(d / ratio)
    assert dims.large.horizontal_m > dims.small.horizontal_m
    assert dims.large.height_m > dims.small.height_m


def test_correction_factor_table_and_interpolation():
    assert wire_correction_factor(0.0005) == pytest.approx(1.045 + 0.5 * (1.053 - 1.045))
    assert wire_correction_factor(0.0035) == pytest.approx(1.064 + 0.5 * (1.068 - 1.064))
    # The diameter is capped at 15 mm before the lookup.
    assert wire_correction_factor(0.015) == pytest.approx(1.068)
    assert wire_correction_factor(0.040) == pytest.approx(1.068)


def test_speed_of_light_option_changes_the_wavelength():
    exact = Qfh(center_frequency_mhz=137.5, diameter_mm=3, bend_radius_mm=15)
    assert exact.dimensions.wavelength_m == pytest.approx(299_792_458 / 137.5e6)
    assert exact.dimensions.wavelength_m < coppens().dimensions.wavelength_m


def test_defaults_and_unit_suffixes():
    q = Qfh(center_frequency_mhz=137.5, diameter_mm=3, bend_radius_mm=15)
    assert (q.turns, q.width_height_ratio, q.handedness) == (0.5, 0.44, "left")
    assert q.diameter_m == pytest.approx(0.003) and q.bend_radius_m == pytest.approx(0.015)


@pytest.mark.parametrize(
    "overrides",
    [
        {"turns": 0},
        {"diameter_mm": -3},
        {"bend_radius_mm": -1},
        {"width_height_ratio": 0},
        {"handedness": "up"},
        {"bend_radius_mm": 500},  # Dc <= 0
        {"max_frequency_mhz": 100},
        {"helix_pieces_per_turn": 2},
        {"unknown": 1},
    ],
)
def test_invalid_parameters(overrides):
    params = {"center_frequency_mhz": 137.5, "diameter_mm": 3, "bend_radius_mm": 15}
    params.update(overrides)
    with pytest.raises(ValidationError):
        Qfh(**params)


# --- NEC2 geometry --------------------------------------------------------------------------


def _loop_path_length(geometry, lo, hi):
    return sum(math.dist(w.start, w.end) for w in geometry.wires[lo:hi])


def test_geometry_structure():
    q = Qfh(center_frequency_mhz=137.5, diameter_mm=3, bend_radius_mm=15)
    g = q.to_geometry()
    pieces = math.ceil(24 * 0.5)  # 12 per arm
    per_loop = 1 + 2 * pieces + 2  # bottom, two arms, two top halves
    assert len(g.wires) == 2 * per_loop + 1  # + the feed wire
    assert len(g.feeds) == 1 and g.feeds[0].wire == len(g.wires) - 1
    feed = g.wires[g.feeds[0].wire]
    assert feed.segments % 2 == 1  # the source sits on the centre segment
    # Tops of both loops meet the feed wire: terminal 1 at its start, terminal 2 at its end.
    top_ends = [w.end for w in g.wires[:-1] if w.end in (feed.start, feed.end)]
    assert len(top_ends) == 4
    assert all(w.radius == pytest.approx(0.0015) for w in g.wires)
    # All wires are above the base plane z = 0 and the large loop starts on it.
    zs = [z for w in g.wires for z in (w.start[2], w.end[2])]
    assert min(zs) == pytest.approx(0.0) and max(zs) > q.dimensions.large.height_m


def test_path_length_matches_the_compensated_length():
    q = Qfh(center_frequency_mhz=137.5, diameter_mm=3, bend_radius_mm=15)
    g = q.to_geometry()
    dims = q.dimensions
    per_loop = 1 + 2 * 12 + 2
    large = _loop_path_length(g, 0, per_loop)
    small = _loop_path_length(g, per_loop, 2 * per_loop)
    # The helix arms are polylines (24 pieces per turn): slightly shorter than the true helix,
    # and the two top halves end at the feed terminals, a few mm off the axis plane.
    assert large == pytest.approx(dims.large.compensated_length_m, rel=0.005)
    assert small == pytest.approx(dims.small.compensated_length_m, rel=0.005)


def test_handedness_mirrors_the_geometry():
    right = Qfh(
        center_frequency_mhz=137.5, diameter_mm=3, bend_radius_mm=15, handedness="right"
    ).to_geometry()
    left = Qfh(
        center_frequency_mhz=137.5, diameter_mm=3, bend_radius_mm=15, handedness="left"
    ).to_geometry()
    assert len(right.wires) == len(left.wires)
    # Mirror image in the xz plane: x and z unchanged, y reversed (the feed on the axis stays).
    for a, b in zip(right.wires, left.wires, strict=True):
        assert (b.start[0], b.start[2]) == pytest.approx((a.start[0], a.start[2]), abs=1e-9)
        assert b.start[1] == pytest.approx(-a.start[1], abs=1e-9)
        assert b.end[1] == pytest.approx(-a.end[1], abs=1e-9)


def test_segmentation_comes_from_core_segmentation():
    q = Qfh(center_frequency_mhz=435, diameter_mm=3, bend_radius_mm=5)
    g = q.to_geometry()
    for w in g.wires[:-1]:
        length = math.dist(w.start, w.end)
        expected = choose_segments(length, w.radius, 435e6, 20.0).segments
        assert w.segments == expected


def test_example_designs_load():
    for name, mhz in (("qfh_137mhz.yaml", 137.5), ("qfh_435mhz.yaml", 435.0)):
        design = load_design(EXAMPLES / name)
        assert isinstance(design.template, Qfh)
        assert design.template.center_frequency_hz == pytest.approx(mhz * 1e6)
        assert design.template.max_frequency_hz >= design.template.center_frequency_hz


# --- NEC2 behaviour (acceptance criteria fixed in advance) -------------------------------------


def run_qfh(f_mhz: float, handedness: str = "left"):
    bend = 15 if f_mhz < 200 else 5
    q = Qfh(
        center_frequency_mhz=f_mhz,
        diameter_mm=3,
        bend_radius_mm=bend,
        handedness=handedness,
    )
    return Nec2Solver(pattern_resolution_deg=10).run(q.to_geometry(), Sweep((f_mhz * 1e6,)))


FREQUENCIES = [137.5, 435.0]
WINDINGS = ["right", "left"]


@pytest.mark.parametrize("handedness", WINDINGS)
@pytest.mark.parametrize("f_mhz", FREQUENCIES)
def test_zenith_axial_ratio_is_below_3_db(f_mhz, handedness):
    assert run_qfh(f_mhz, handedness).zenith_axial_ratio_db[0] < 3.0


@pytest.mark.parametrize("f_mhz", FREQUENCIES)
def test_left_winding_is_rhcp_and_right_winding_is_lhcp_at_the_zenith(f_mhz):
    # Feed at the top, towards +z. The 10 dB margin is far below what AR < 3 dB implies (15 dB).
    left = run_qfh(f_mhz, "left")
    assert left.zenith_rhcp_gain_dbic[0] > left.zenith_lhcp_gain_dbic[0] + 10
    right = run_qfh(f_mhz, "right")
    assert right.zenith_lhcp_gain_dbic[0] > right.zenith_rhcp_gain_dbic[0] + 10


@pytest.mark.parametrize("f_mhz", FREQUENCIES)
def test_reversing_the_winding_reverses_the_dominant_circular_sense(f_mhz):
    def dominant_is_rhcp(result):
        return result.zenith_rhcp_gain_dbic[0] > result.zenith_lhcp_gain_dbic[0]

    assert dominant_is_rhcp(run_qfh(f_mhz, "right")) != dominant_is_rhcp(run_qfh(f_mhz, "left"))


@pytest.mark.parametrize("f_mhz", FREQUENCIES)
def test_beam_points_up_and_the_nadir_is_not_circular(f_mhz):
    # With the small loop's feed polarity wrong, the beam and the good circular polarisation
    # were straight down (nadir AR 0.90 / 0.39 dB). Now the beam is on the zenith side and the
    # nadir is clearly worse than 3 dB.
    result = run_qfh(f_mhz)
    theta_peak, _ = result.max_gain_direction_rad[0]
    assert theta_peak < math.pi / 2
    assert result.axial_ratio_db[0, -1, 0] > 3.0  # theta = 180 degrees
    assert result.axial_ratio_db[0, -1, 0] > result.zenith_axial_ratio_db[0]
