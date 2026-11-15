import json
import math
from pathlib import Path

import pytest

from antennamax.cli.main import main
from antennamax.io.design import DesignError, load_design
from antennamax.templates import Dipole, Yagi

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "design.yaml"
    path.write_text(text, encoding="utf-8")
    return path


VALID_DIPOLE = """\
template: dipole
params:
  center_frequency_mhz: 145
  diameter_mm: 4
sweep:
  start_mhz: 144
  stop_mhz: 146
  points: 3
"""


# --- Loading -----------------------------------------------------------------------------


def test_load_dipole_example():
    d = load_design(EXAMPLES / "dipole_145mhz.yaml")
    assert d.template_name == "dipole"
    assert isinstance(d.template, Dipole)
    assert d.template.center_frequency_hz == pytest.approx(145e6)
    assert d.template.diameter_m == pytest.approx(0.004)
    assert len(d.sweep.frequencies_hz) == 11
    assert d.sweep.frequencies_hz[0] == pytest.approx(140e6)
    assert d.sweep.frequencies_hz[-1] == pytest.approx(150e6)
    assert d.pattern_resolution_deg == 10


def test_load_yagi_example():
    d = load_design(EXAMPLES / "yagi3_144mhz.yaml")
    assert isinstance(d.template, Yagi)
    assert len(d.template.elements) == 3
    assert d.template.feed_index == 1
    assert d.template.elements[1].position_m == pytest.approx(0.3)


def test_pattern_is_optional(tmp_path):
    d = load_design(_write(tmp_path, VALID_DIPOLE))
    assert d.pattern_resolution_deg is None


def test_si_and_unit_suffix_inputs_are_equivalent(tmp_path):
    si = VALID_DIPOLE.replace("center_frequency_mhz: 145", "center_frequency_hz: 145000000")
    si = si.replace("diameter_mm: 4", "diameter_m: 0.004").replace("_mhz:", "_hz:")
    si = si.replace("start_hz: 144", "start_hz: 144000000").replace(
        "stop_hz: 146", "stop_hz: 146000000"
    )
    a = load_design(_write(tmp_path, VALID_DIPOLE))
    b = load_design(_write(tmp_path, si))
    assert a.template == b.template
    assert a.sweep.frequencies_hz == pytest.approx(b.sweep.frequencies_hz)


# --- Errors ------------------------------------------------------------------------------


def test_unknown_template(tmp_path):
    path = _write(tmp_path, VALID_DIPOLE.replace("template: dipole", "template: quad"))
    with pytest.raises(DesignError) as err:
        load_design(path)
    msg = str(err.value)
    assert "unknown template 'quad'" in msg
    assert "dipole" in msg and "yagi" in msg
    assert str(path) in msg


def test_invalid_params_message_names_the_field(tmp_path):
    path = _write(tmp_path, VALID_DIPOLE.replace("diameter_mm: 4", "diameter_mm: -4"))
    with pytest.raises(DesignError) as err:
        load_design(path)
    assert "params.diameter_m" in str(err.value)


def test_invalid_nested_yagi_params(tmp_path):
    text = (EXAMPLES / "yagi3_144mhz.yaml").read_text(encoding="utf-8")
    path = _write(tmp_path, text.replace("feed_index: 1", "feed_index: 7"))
    with pytest.raises(DesignError, match="feed_index is out of range"):
        load_design(path)


@pytest.mark.parametrize(
    ("old", "new", "fragment"),
    [
        ("points: 3", "points: 0", "sweep.points"),
        ("stop_mhz: 146", "stop_mhz: 100", "stop must not be smaller"),
        ("sweep:", "sweeep:", "sweep"),  # missing section
        ("points: 3", "points: 3\npattern:\n  resolution_deg: 7", "pattern.resolution_deg"),
        ("template: dipole", "template: dipole\nbogus: 1", "bogus"),
    ],
)
def test_invalid_design_sections(tmp_path, old, new, fragment):
    path = _write(tmp_path, VALID_DIPOLE.replace(old, new))
    with pytest.raises(DesignError) as err:
        load_design(path)
    assert fragment in str(err.value)


def test_broken_yaml_and_wrong_shape_and_missing_file(tmp_path):
    with pytest.raises(DesignError, match="invalid YAML"):
        load_design(_write(tmp_path, "template: [unclosed"))
    with pytest.raises(DesignError, match="must be a mapping"):
        load_design(_write(tmp_path, "- just\n- a list\n"))
    with pytest.raises(DesignError, match="cannot read"):
        load_design(tmp_path / "missing.yaml")


# --- CLI (main() called directly) --------------------------------------------------------


def test_cli_table_with_pattern(capsys):
    code = main(["run", str(EXAMPLES / "yagi3_144mhz.yaml")])
    out = capsys.readouterr().out
    assert code == 0
    assert "template: yagi" in out
    assert "SWR" in out and "Gmax[dBi]" in out and "F/B[dB]" in out
    rows = [line for line in out.splitlines() if line.strip().startswith(("142", "144", "146"))]
    assert len(rows) == 3
    # The 144 MHz row: R, X, SWR, Gmax, F/B are all numbers.
    fields = [line for line in rows if line.split()[0] == "144.000"][0].split()
    assert len(fields) == 9  # f, R, X, SWR, Gmax, F/B, AR(z), RHCP(z), LHCP(z)
    assert float(fields[4]) > 5.0  # Gmax of a 3-element beam [dBi]
    assert float(fields[5]) > 0.0  # F/B [dB]


def test_cli_table_without_pattern(tmp_path, capsys):
    code = main(["run", str(_write(tmp_path, VALID_DIPOLE))])
    out = capsys.readouterr().out
    assert code == 0
    assert "SWR" in out
    assert "Gmax" not in out and "F/B" not in out
    assert len([ln for ln in out.splitlines() if ln.strip().startswith("14")]) == 3


def test_cli_json_roundtrip(capsys):
    code = main(["run", str(EXAMPLES / "dipole_145mhz.yaml"), "--json"])
    out = capsys.readouterr().out
    assert code == 0

    def reject(token):  # json.loads accepts NaN/Infinity by default; the output must not use them
        raise AssertionError(f"non-standard JSON constant {token}")

    data = json.loads(out, parse_constant=reject)
    assert data["template"] == "dipole"
    r = data["result"]
    assert len(r["frequencies_hz"]) == len(r["impedance_real"]) == len(r["swr"]) == 11
    assert r["z0"] == 50.0
    assert len(r["theta_rad"]) == 19 and len(r["phi_rad"]) == 36
    assert len(r["gain_dbi"]) == 11 and len(r["gain_dbi"][0]) == 19
    # The dipole lies along y: the null on its axis (theta = 90, phi = 90 deg; -inf) is
    # serialised as null, and the peak is about 2.15 dBi.
    assert r["gain_dbi"][0][9][9] is None
    assert all(math.isclose(g, 2.15, abs_tol=0.15) for g in r["max_gain_dbi"])
    # A dipole is symmetric: front and back gains are equal, so F/B is 0 dB.
    assert all(math.isclose(v, 0.0, abs_tol=1e-6) for v in r["front_to_back_db"])


def test_cli_json_without_pattern(tmp_path, capsys):
    assert main(["run", str(_write(tmp_path, VALID_DIPOLE)), "--json"]) == 0
    r = json.loads(capsys.readouterr().out)["result"]
    assert r["gain_dbi"] is None and r["front_to_back_db"] is None
    assert len(r["swr"]) == 3


def test_cli_reports_design_errors(tmp_path, capsys):
    bad = _write(tmp_path, VALID_DIPOLE.replace("template: dipole", "template: quad"))
    code = main(["run", str(bad)])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "unknown template 'quad'" in captured.err
