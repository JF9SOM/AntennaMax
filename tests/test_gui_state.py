"""The GUI's logic without Qt: form generation from the models, units, validation, files."""

import pytest

from antennamax.gui import schema, state
from antennamax.gui.calc import compute_design

ROOT_EXAMPLES = "examples"


def test_fields_are_generated_from_the_models():
    names = {f.name: f for f in schema.template_fields("qfh")}
    assert names["center_frequency_hz"].unit == "MHz"
    assert names["diameter_m"].unit == "mm"
    assert names["handedness"].kind == "choice"
    assert {f.name for f in schema.template_fields("yagi")} >= {"elements"}


def test_units_are_converted_at_the_boundary():
    values = state.default_values("dipole")
    values.fields["center_frequency_hz"] = "145"
    design, mapping, errors = state.validate(values)
    assert not errors and design is not None
    assert design.template.center_frequency_hz == pytest.approx(145e6)


def test_bad_number_is_reported_at_its_field_without_raising():
    values = state.default_values("dipole")
    values.fields["center_frequency_hz"] = "abc"
    design, mapping, errors = state.validate(values)
    assert design is None
    assert any(e.target == ("field", "center_frequency_hz") for e in errors)


def test_negative_value_is_reported_at_its_field():
    values = state.default_values("dipole")
    values.fields["diameter_m"] = "-1"
    design, _, errors = state.validate(values)
    assert design is None
    assert any(e.target[:2] == ("field", "diameter_m") for e in errors)


def test_bad_sweep_is_reported_at_the_sweep():
    values = state.default_values("dipole")
    values.sweep_points = "0"
    design, _, errors = state.validate(values)
    assert design is None
    assert any(e.target[0] == "sweep" for e in errors)


def test_file_round_trip_keeps_the_design():
    values = state.values_from_file("examples/yagi3_144mhz.yaml")
    assert values.template == "yagi" and len(values.rows) == 3
    design, mapping, errors = state.validate(values)
    assert not errors
    again = state.mapping_to_yaml(mapping)
    assert "elements" in again


def test_compute_design_returns_a_run_and_never_raises():
    values = state.values_from_file("examples/qfh_137mhz.yaml")
    _, mapping, _ = state.validate(values)
    outcome = compute_design(mapping)
    assert outcome.error is None and outcome.run is not None
    bad = compute_design({"template": "nope"})
    assert bad.run is None and bad.error
