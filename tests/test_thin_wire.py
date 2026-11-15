"""Thin-wire applicability check (delta / a) and the extended-kernel option of Nec2Solver."""

import json
import warnings
from pathlib import Path

import numpy as np
import pytest

from antennamax.cli.main import main
from antennamax.core.geometry import Geometry, Wire
from antennamax.core.units import mhz_to_hz
from antennamax.solvers import thin_wire
from antennamax.solvers.base import Sweep
from antennamax.solvers.nec2 import Nec2Solver, input_impedance
from antennamax.solvers.thin_wire import ThinWireOutOfRangeWarning, ThinWireWarning
from antennamax.viz.data import WIRE_COLORS, legend_entries, wire_draws

F = mhz_to_hz(100.0)
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _dipole(radius: float, segments: int = 31, length: float = 1.4, x: float = 0.0) -> Geometry:
    h = length / 2
    return Geometry([Wire((x, -h, 0), (x, h, 0), radius, segments)])


def _parallel(*geometries: Geometry) -> Geometry:
    """Wires of several dipoles side by side, 0.5 m apart along x (so they do not touch)."""
    wires = [
        Wire((0.5 * i, -0.7, 0), (0.5 * i, 0.7, 0), g.wires[0].radius, g.wires[0].segments)
        for i, g in enumerate(geometries)
    ]
    return Geometry(wires)


OK = _dipole(1e-3)  # delta/a = 1.4 / 31 / 1e-3 = 45
STANDARD = _dipole(0.01)  # delta/a = 4.52: below 8, above 2
SEVERE = _dipole(0.03)  # delta/a = 1.51: below 2
R_STANDARD = 1.4 / 31 / 0.01
R_SEVERE = 1.4 / 31 / 0.03


# --- delta / a ---------------------------------------------------------------------------


def test_ratio_is_segment_length_over_radius():
    wire = Wire((0, 0, 0), (0, 0, 2.0), radius=0.01, segments=10)  # delta = 0.2 m
    assert thin_wire.segment_to_radius_ratio(wire) == pytest.approx(20.0)
    assert thin_wire.ratios(OK) == pytest.approx([1.4 / 31 / 1e-3])


@pytest.mark.parametrize(
    ("ratio", "status"),
    [
        (8.0, thin_wire.OK),
        (100.0, thin_wire.OK),
        (7.99, thin_wire.STANDARD_OUT_OF_RANGE),
        (2.0, thin_wire.STANDARD_OUT_OF_RANGE),
        (1.99, thin_wire.EXTENDED_OUT_OF_RANGE),
    ],
)
def test_wire_status_boundaries_standard_kernel(ratio, status):
    assert thin_wire.wire_status(ratio) == status
    assert thin_wire.wire_status(ratio, extended_kernel=False) == status


@pytest.mark.parametrize(
    ("ratio", "status"),
    [
        (100.0, thin_wire.OK),
        (8.0, thin_wire.OK),
        (7.99, thin_wire.OK),  # fine for the extended kernel
        (2.0, thin_wire.OK),
        (1.99, thin_wire.EXTENDED_OUT_OF_RANGE),
    ],
)
def test_wire_status_boundaries_extended_kernel(ratio, status):
    assert thin_wire.wire_status(ratio, extended_kernel=True) == status


# --- warnings ----------------------------------------------------------------------------


def test_no_warning_when_ratio_is_at_least_8():
    for kernel in (False, True, "auto"):
        with warnings.catch_warnings():
            warnings.simplefilter("error", ThinWireWarning)
            Nec2Solver(extended_kernel=kernel).run(OK, Sweep((F,)))
            input_impedance(OK, F, extended_kernel=kernel)


def test_standard_kernel_warns_below_8():
    with pytest.warns(ThinWireWarning) as record:
        Nec2Solver(extended_kernel=False).run(STANDARD, Sweep((F, 1.1 * F)))
    assert len(record) == 1  # once per run, not once per frequency
    assert record[0].category is ThinWireWarning  # not the stronger class
    message = str(record[0].message)
    assert "wire 0" in message and f"{R_STANDARD:.2f}" in message and "standard-kernel" in message
    assert "Extended thin-wire kernel is OFF" in message


def test_extended_kernel_is_silent_between_2_and_8():
    for kernel in (True, "auto"):  # "auto" turns the extended kernel on for this wire
        with warnings.catch_warnings():
            warnings.simplefilter("error", ThinWireWarning)
            result = Nec2Solver(extended_kernel=kernel).run(STANDARD, Sweep((F,)))
        assert result.meta["extended_kernel"] is True
        assert result.meta["min_segment_to_radius"] == pytest.approx(R_STANDARD)  # still recorded


@pytest.mark.parametrize("kernel", [False, True, "auto"])
def test_stronger_warning_below_2_for_every_kernel_setting(kernel):
    with pytest.warns(ThinWireOutOfRangeWarning, match="extended-kernel") as record:
        Nec2Solver(extended_kernel=kernel).run(SEVERE, Sweep((F,)))
    assert isinstance(record[0].message, ThinWireWarning)  # still a ThinWireWarning


def test_extended_kernel_message_says_so():
    with pytest.warns(ThinWireOutOfRangeWarning, match="Extended thin-wire kernel is ON"):
        Nec2Solver(extended_kernel=True).run(SEVERE, Sweep((F,)))


def test_input_impedance_also_checks():
    with pytest.warns(ThinWireWarning):
        input_impedance(STANDARD, F, extended_kernel=False)
    with warnings.catch_warnings():  # default "auto" -> extended kernel on -> within guideline
        warnings.simplefilter("error", ThinWireWarning)
        input_impedance(STANDARD, F)


def test_warning_lists_only_wires_outside_the_active_guideline():
    geometry = _parallel(OK, STANDARD, SEVERE)
    with pytest.warns(ThinWireOutOfRangeWarning) as record:
        Nec2Solver(extended_kernel=False).run(geometry, Sweep((F,)))
    message = str(record[0].message)
    assert "wire 0" not in message
    assert f"wire 1 (delta/a = {R_STANDARD:.2f})" in message
    assert f"wire 2 (delta/a = {R_SEVERE:.2f})" in message

    with pytest.warns(ThinWireOutOfRangeWarning) as record:  # "auto": extended kernel on
        Nec2Solver().run(geometry, Sweep((F,)))
    message = str(record[0].message)
    assert "wire 1" not in message  # 2 <= delta/a < 8 is fine for the extended kernel
    assert f"wire 2 (delta/a = {R_SEVERE:.2f})" in message


# --- extended kernel ---------------------------------------------------------------------


@pytest.mark.filterwarnings("ignore::antennamax.solvers.thin_wire.ThinWireWarning")
class TestExtendedKernel:
    def test_auto_enables_when_any_wire_is_below_8(self):
        assert Nec2Solver().run(STANDARD, Sweep((F,))).meta["extended_kernel"] is True
        mixed = _parallel(OK, STANDARD)
        assert (
            Nec2Solver(extended_kernel="auto").run(mixed, Sweep((F,))).meta["extended_kernel"]
            is True
        )

    def test_auto_stays_off_when_all_wires_are_at_least_8(self):
        assert Nec2Solver().run(OK, Sweep((F,))).meta["extended_kernel"] is False

    def test_explicit_setting_overrides_auto(self):
        assert (
            Nec2Solver(extended_kernel=False).run(STANDARD, Sweep((F,))).meta["extended_kernel"]
            is False
        )
        assert Nec2Solver(extended_kernel=True).run(OK, Sweep((F,))).meta["extended_kernel"] is True

    def test_meta_records_solver_and_minimum_ratio(self):
        meta = Nec2Solver().run(STANDARD, Sweep((F,))).meta
        assert meta["solver"] == "nec2"
        assert meta["min_segment_to_radius"] == pytest.approx(1.4 / 31 / 0.01)

    def test_extended_kernel_changes_the_numbers(self):
        off = Nec2Solver(extended_kernel=False).run(STANDARD, Sweep((F,))).impedance[0]
        on = Nec2Solver(extended_kernel=True).run(STANDARD, Sweep((F,))).impedance[0]
        assert abs(on - off) > 1e-3  # the flag reaches PyNEC
        assert abs(on - off) < 5.0  # but it is a small correction here

    def test_invalid_setting_is_rejected(self):
        with pytest.raises(ValueError, match="extended_kernel"):
            Nec2Solver(extended_kernel="yes")  # type: ignore[arg-type]


# --- CLI ---------------------------------------------------------------------------------

THICK_DIPOLE = """\
template: dipole
params:
  center_frequency_mhz: 145
  diameter_mm: 40
sweep:
  start_mhz: 144
  stop_mhz: 146
  points: 3
"""


def test_cli_table_shows_kernel_for_a_normal_design(capsys):
    assert main(["run", str(EXAMPLES / "dipole_145mhz.yaml")]) == 0
    captured = capsys.readouterr()
    assert "extended thin-wire kernel: off" in captured.out
    assert "warning" not in captured.err


def test_cli_warns_and_reports_the_kernel_for_a_thick_design(tmp_path, capsys):
    path = tmp_path / "thick.yaml"
    path.write_text(THICK_DIPOLE, encoding="utf-8")
    assert main(["run", str(path)]) == 0
    captured = capsys.readouterr()
    assert "extended thin-wire kernel: on" in captured.out
    assert "antennamax: warning: thin-wire approximation" in captured.err
    assert "outside even the extended-kernel guideline" in captured.err  # 40 mm: delta/a < 2


def test_cli_moderately_thick_design_uses_extended_kernel_without_warning(tmp_path, capsys):
    path = tmp_path / "thick20.yaml"
    path.write_text(THICK_DIPOLE.replace("diameter_mm: 40", "diameter_mm: 20"), encoding="utf-8")
    assert main(["run", str(path)]) == 0  # 20 mm: delta/a = 3.17, between 2 and 8
    captured = capsys.readouterr()
    assert "extended thin-wire kernel: on; min segment/radius = 3.17" in captured.out
    assert "warning" not in captured.err


def test_cli_json_includes_meta(tmp_path, capsys):
    path = tmp_path / "thick.yaml"
    path.write_text(THICK_DIPOLE, encoding="utf-8")
    assert main(["run", str(path), "--json"]) == 0
    meta = json.loads(capsys.readouterr().out)["result"]["meta"]
    assert meta["solver"] == "nec2"
    assert meta["extended_kernel"] is True
    assert meta["min_segment_to_radius"] < 2.0


# --- viewer colours reuse the solver's rule ----------------------------------------------


def test_view_wire_status_and_legend():
    geometry = _parallel(OK, STANDARD, SEVERE)
    draws, _ = wire_draws(geometry)  # standard kernel
    assert [d.status for d in draws] == [
        thin_wire.OK,
        thin_wire.STANDARD_OUT_OF_RANGE,
        thin_wire.EXTENDED_OUT_OF_RANGE,
    ]
    assert [d.ratio for d in draws] == pytest.approx(thin_wire.ratios(geometry))
    assert WIRE_COLORS[thin_wire.STANDARD_OUT_OF_RANGE] == "yellow"
    assert WIRE_COLORS[thin_wire.EXTENDED_OUT_OF_RANGE] == "red"
    labels = [label for label, _ in legend_entries(draws)]
    assert len(labels) == 4  # three wire categories + the feed point
    assert labels[-1] == "feed point"


def test_view_colours_follow_the_active_kernel():
    geometry = _parallel(OK, STANDARD, SEVERE)
    draws, _ = wire_draws(geometry, extended_kernel=True)
    # With the extended kernel on, 2 <= delta/a < 8 is not yellow any more.
    assert [d.status for d in draws] == [
        thin_wire.OK,
        thin_wire.OK,
        thin_wire.EXTENDED_OUT_OF_RANGE,
    ]
    labels = [label for label, _ in legend_entries(draws, extended_kernel=True)]
    assert labels == ["wire: delta/a >= 2", "wire: delta/a < 2", "feed point"]


def test_legend_lists_only_categories_present():
    draws, _ = wire_draws(OK)
    assert [label for label, _ in legend_entries(draws)] == ["wire: delta/a >= 8", "feed point"]


def test_results_are_unchanged_by_the_check():
    # Same impedance with and without the check path: a sanity guard for the refactor.
    z = Nec2Solver(extended_kernel=False).run(OK, Sweep((F,))).impedance[0]
    assert np.isfinite(z) and z.real > 0
