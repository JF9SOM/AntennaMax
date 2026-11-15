"""core.segmentation: segment counts under 'segment < lambda/10' and 'delta/a > 2'."""

import math

import pytest
from pydantic import ValidationError

from antennamax.cli.main import main
from antennamax.core.segmentation import (
    Reason,
    SegmentationError,
    choose_common_segments,
    choose_segments,
)
from antennamax.io.design import load_design
from antennamax.templates import Dipole, Yagi

C = 299_792_458.0


def _check_constraints(n, length, radius, f_hz):
    wavelength = C / f_hz
    delta = length / n
    assert delta < wavelength / 10, "segment must be shorter than lambda/10"
    assert delta / radius > 2, "delta/a must exceed 2"


# --- single wire --------------------------------------------------------------------------


def test_target_density_is_used_when_it_is_allowed():
    # 1 m wire at 145 MHz: lambda = 2.067 m, 20 per wavelength -> 9.7 -> 10 -> odd 11.
    s = choose_segments(1.0, 0.002, 145e6, odd=True)
    assert (s.segments, s.reason) == (11, Reason.TARGET_DENSITY)
    assert s.n_target == 11 and s.n_min < 11 < s.n_max
    assert choose_segments(1.0, 0.002, 145e6).segments == 10  # even allowed without `odd`
    _check_constraints(s.segments, 1.0, 0.002, 145e6)


def test_density_is_raised_to_keep_segments_shorter_than_a_tenth_of_a_wavelength():
    # Only 5 segments per wavelength requested, but lambda/10 needs more.
    s = choose_segments(1.0, 0.002, 145e6, segments_per_wavelength=5.0)
    assert s.reason is Reason.MAX_SEGMENT_LENGTH
    # lambda = 2.067 m: 5 per wavelength -> 3 segments, but delta < lambda/10 needs N >= 5.
    assert s.segments == s.n_min == 5 and s.n_target == 3
    _check_constraints(s.segments, 1.0, 0.002, 145e6)


def test_density_is_reduced_to_keep_delta_over_a_above_2():
    # 0.102 m wire at 1296 MHz with 6 mm radius: delta/a > 2 allows at most 8 -> odd 7.
    s = choose_segments(0.1022, 0.006, 1296e6, odd=True)
    assert s.reason is Reason.SEGMENT_TO_RADIUS
    assert s.n_target > s.n_max == s.segments == 7
    _check_constraints(s.segments, 0.1022, 0.006, 1296e6)


def test_odd_option_rounds_into_the_window():
    s = choose_segments(1.0, 0.002, 145e6, segments_per_wavelength=20.0, odd=True)
    assert s.segments % 2 == 1 and s.n_min % 2 == 1 and s.n_max % 2 == 1


def test_boundaries_are_strict():
    # delta/a must be > 2: a wire with L/(2a) = 10 exactly allows N <= 9, not 10.
    s = choose_segments(1.0, 0.05, 1e6, segments_per_wavelength=1000.0)
    assert s.n_max == 9
    # delta < lambda/10: L/lambda = 0.5 exactly -> N > 5.
    s = choose_segments(1.0, 1e-4, C / 2.0, segments_per_wavelength=1.0)
    assert s.n_min == 6


def test_impossible_combination_raises_segmentation_error():
    # 0.1022 m wire, 15 mm radius at 1296 MHz: lambda/10 needs >= 5, delta/a > 2 allows <= 3.
    with pytest.raises(SegmentationError) as err:
        choose_segments(0.1022, 0.015, 1296e6)
    message = str(err.value)
    assert "cannot segment" in message and "1296 MHz" in message
    assert "at least 5" in message and "at most 3" in message
    assert isinstance(err.value, ValueError)


def test_odd_counts_can_make_a_feasible_window_infeasible():
    # Window [6, 7] -> odd {7} is fine; window [6, 6] has no odd count.
    wavelength = C / 1e9
    length = 0.55 * wavelength  # n_min = floor(5.5) + 1 = 6
    radius = length / (2 * 6.5)  # n_max = ceil(6.5) - 1 = 6
    assert choose_segments(length, radius, 1e9).segments == 6
    with pytest.raises(SegmentationError, match="odd counts only"):
        choose_segments(length, radius, 1e9, odd=True)


@pytest.mark.parametrize(
    "args",
    [(-1.0, 0.002, 1e8), (1.0, 0.0, 1e8), (1.0, 0.002, 0.0)],
)
def test_invalid_inputs(args):
    with pytest.raises(ValueError):
        choose_segments(*args)


# --- several wires (yagi) -----------------------------------------------------------------


def test_common_count_is_driven_by_the_most_demanding_wires():
    lengths = [(1.03, 0.003), (0.98, 0.003), (0.92, 0.003)]
    s = choose_common_segments(lengths, 144e6, odd=True)
    assert s.segments == 11 and s.limiting_wire == 0  # target comes from the longest wire
    # A thick short wire sets the upper bound instead: ceil(0.3 / 0.04) - 1 = 7.
    s = choose_common_segments([(1.03, 0.003), (0.3, 0.02)], 144e6, odd=True)
    assert s.limiting_wire == 1 and s.reason is Reason.SEGMENT_TO_RADIUS
    assert s.segments == s.n_max == 7 < s.n_target


# --- Yagi: the cases of the earlier analysis table ----------------------------------------


def _yagi(f_mhz, dia_mm):
    # The bundled 144 MHz shape, scaled in length and spacing to the frequency.
    k = 144 / f_mhz
    return Yagi(
        center_frequency_mhz=f_mhz,
        feed_index=1,
        elements=[
            {"position_mm": 0, "length_mm": 1030 * k, "diameter_mm": dia_mm},
            {"position_mm": 300 * k, "length_mm": 980 * k, "diameter_mm": dia_mm},
            {"position_mm": 600 * k, "length_mm": 920 * k, "diameter_mm": dia_mm},
        ],
    )


@pytest.mark.parametrize(
    ("f_mhz", "dia_mm"),
    [(144, 6), (144, 12), (144, 19), (144, 25), (144, 50), (430, 6), (430, 12), (1296, 6)],
)
def test_yagi_table_cases_follow_the_target_density(f_mhz, dia_mm):
    # delta/a > 2 is no obstacle for any of these (it was delta/a < 8 that they violated),
    # so the count is the 20-per-wavelength target: ceil(20 * 1.03/2.082) = 10 -> odd 11.
    y = _yagi(f_mhz, dia_mm)
    s = y.segmentation
    assert (s.segments, s.reason) == (11, Reason.TARGET_DENSITY)
    assert y.segments == 11
    for e in y.elements:
        _check_constraints(s.segments, e.length_m, e.diameter_m / 2, f_mhz * 1e6)


def test_yagi_with_very_thick_elements_at_uhf_is_reduced():
    y = _yagi(1296, 12)  # the shortest element allows only delta/a > 2 up to 7 segments
    s = y.segmentation
    assert s.reason is Reason.SEGMENT_TO_RADIUS and s.segments == 7 < s.n_target
    for e in y.elements:
        _check_constraints(s.segments, e.length_m, e.diameter_m / 2, 1296e6)
    geometry = y.to_geometry()
    assert {w.segments for w in geometry.wires} == {7}  # same N on every element


def test_yagi_that_cannot_be_segmented_raises():
    y = _yagi(1296, 30)
    with pytest.raises(SegmentationError, match="cannot segment"):
        y.to_geometry()


def test_yagi_segmentation_uses_the_highest_frequency():
    low = _yagi(144, 6)
    high = Yagi(**{**low.model_dump(), "max_frequency_hz": 200e6})
    assert high.segments > low.segments  # shorter wavelength -> more segments
    with pytest.raises(ValidationError, match="max_frequency_hz"):
        Yagi(**{**low.model_dump(), "max_frequency_hz": 100e6})


def test_bundled_yagi_example_keeps_its_segment_count():
    design = load_design("examples/yagi3_144mhz.yaml")
    assert design.template.segments == 11  # unchanged from the earlier fixed rule
    assert design.template.max_frequency_hz == pytest.approx(146e6)  # top of the sweep


# --- Dipole -------------------------------------------------------------------------------


def test_dipole_without_segments_uses_the_automatic_choice():
    d = Dipole(center_frequency_mhz=145.0, diameter_mm=4)
    assert d.segmentation is not None and d.segmentation.reason is Reason.TARGET_DENSITY
    assert d.resolved_segments == d.segmentation.segments == 11
    assert d.to_geometry().wires[0].segments == 11


def test_dipole_with_explicit_segments_is_used_as_is():
    d = Dipole(center_frequency_mhz=145.0, diameter_mm=4, segments=31)
    assert d.segmentation is None and d.resolved_segments == 31
    # Even a count that violates the constraints is accepted (the solver only warns).
    coarse = Dipole(center_frequency_mhz=145.0, diameter_mm=40, segments=101)
    assert coarse.to_geometry().wires[0].segments == 101


def test_dipole_follows_the_top_of_the_sweep():
    centre = Dipole(center_frequency_mhz=145.0, diameter_mm=4)
    wide = Dipole(center_frequency_mhz=145.0, diameter_mm=4, max_frequency_mhz=450.0)
    assert wide.resolved_segments > centre.resolved_segments


def test_dipole_that_cannot_be_segmented_raises():
    d = Dipole(center_frequency_mhz=1296.0, length_mm=102, diameter_mm=30)
    with pytest.raises(SegmentationError):
        d.to_geometry()


# --- loader and CLI -----------------------------------------------------------------------


def test_loader_passes_the_sweep_top_to_templates(tmp_path):
    path = tmp_path / "d.yaml"
    path.write_text(
        "template: dipole\nparams: {center_frequency_mhz: 145, diameter_mm: 4}\n"
        "sweep: {start_mhz: 140, stop_mhz: 450, points: 3}\n",
        encoding="utf-8",
    )
    d = load_design(path)
    assert d.template.max_frequency_hz == pytest.approx(450e6)
    assert d.template.resolved_segments > 11
    # An explicit value in params wins.
    path.write_text(
        "template: dipole\nparams: {center_frequency_mhz: 145, diameter_mm: 4,"
        " max_frequency_mhz: 146}\nsweep: {start_mhz: 140, stop_mhz: 450, points: 3}\n",
        encoding="utf-8",
    )
    assert load_design(path).template.max_frequency_hz == pytest.approx(146e6)


def test_cli_reports_a_segmentation_error(tmp_path, capsys):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "template: dipole\nparams: {center_frequency_mhz: 1296, length_mm: 102, diameter_mm: 30}\n"
        "sweep: {start_mhz: 1290, stop_mhz: 1300, points: 2}\n",
        encoding="utf-8",
    )
    assert main(["run", str(path)]) == 2
    captured = capsys.readouterr()
    assert "antennamax: error: cannot segment" in captured.err
    assert captured.out == ""


def test_math_sanity_of_the_bounds():
    # n_min / n_max reproduce the defining inequalities for a spread of inputs.
    for length in (0.1, 0.5, 1.0, 3.0):
        for radius in (1e-4, 1e-3, 1e-2):
            for f in (3e7, 1.45e8, 4.3e8, 1.296e9):
                try:
                    s = choose_segments(length, radius, f)
                except SegmentationError:
                    continue
                _check_constraints(s.segments, length, radius, f)
                assert s.n_min <= s.segments <= s.n_max
                assert math.isfinite(s.segments)
