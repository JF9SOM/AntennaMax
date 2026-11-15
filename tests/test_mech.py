"""3D-printable parts: the QFH spreader (build123d, extra `cad`).

Tests that build a shape are skipped when build123d is not installed.
"""

import struct
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from antennamax.cli.main import main
from antennamax.mech import base
from antennamax.mech.qfh_spreader import DEFAULT_MAST_OUTER_DIAMETER_M, QfhSpreader
from antennamax.templates.qfh import Qfh

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def qfh137() -> Qfh:
    return Qfh(center_frequency_mhz=137.5, diameter_mm=3, bend_radius_mm=15)


def spreader(**overrides) -> QfhSpreader:
    params = {"qfh": qfh137()}
    params.update(overrides)
    return QfhSpreader(**params)


def need_cad():
    return pytest.importorskip("build123d")


# --- parameters and derived dimensions (no CAD needed) ---------------------------------------


def test_hole_diameters_are_conductor_plus_clearance():
    s = spreader()
    assert s.print_settings.clearance_m == pytest.approx(0.0002)  # default 0.2 mm
    assert s.conductor_hole_diameter_m == pytest.approx(0.0032)  # 3 mm + 0.2 mm
    assert s.mast_hole_diameter_m == pytest.approx(DEFAULT_MAST_OUTER_DIAMETER_M + 0.0002)
    wide = spreader(print_settings={"clearance_mm": 0.4})
    assert wide.conductor_hole_diameter_m == pytest.approx(0.0034)
    assert wide.mast_hole_diameter_m == pytest.approx(DEFAULT_MAST_OUTER_DIAMETER_M + 0.0004)
    assert spreader(print_settings={"clearance_mm": 0}).conductor_hole_diameter_m == pytest.approx(
        0.003
    )


def test_default_arm_and_plate_dimensions_follow_the_hole_diameter():
    s = spreader()
    hole = s.conductor_hole_diameter_m
    assert s.resolved_arm_width_m == pytest.approx(3 * hole)
    assert s.resolved_thickness_m == pytest.approx(2 * hole)
    assert s.resolved_end_margin_m == pytest.approx(hole)
    custom = spreader(arm_width_mm=12, thickness_mm=8, end_margin_mm=5)
    assert (custom.resolved_arm_width_m, custom.resolved_thickness_m) == pytest.approx(
        (0.012, 0.008)
    )
    assert custom.resolved_end_margin_m == pytest.approx(0.005)


def test_hole_centres_come_from_the_qfh_dimensions():
    s = spreader()
    dims = s.qfh.dimensions
    a, b = dims.large.horizontal_m / 2, dims.small.horizontal_m / 2
    assert s.hole_centers_m == [(a, 0.0), (-a, 0.0), (0.0, b), (0.0, -b)]
    assert a > b > 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"mast_outer_diameter_mm": 500},  # the hub would swallow the holes
        {"mast_outer_diameter_mm": 0},
        {"arm_width_mm": 1},  # narrower than the hole
        {"thickness_mm": -1},
        {"print_settings": {"clearance_mm": -0.1}},
        {"unknown": 1},
    ],
)
def test_invalid_parameters(overrides):
    with pytest.raises(ValidationError):
        spreader(**overrides)


# --- shape ----------------------------------------------------------------------------------


def test_bounding_box_matches_the_large_loop_dimension():
    need_cad()
    s = spreader()
    box = s.build().bounding_box()
    dims = s.qfh.dimensions
    hole = 3.0 + 0.2  # conductor + clearance, mm
    # x: the large-loop arm, D1 between hole centres plus a hole and a margin (= hole) each end
    assert box.size.X == pytest.approx(dims.large.horizontal_m * 1000 + hole + 2 * hole, abs=1e-3)
    # y: the small-loop arm
    assert box.size.Y == pytest.approx(dims.small.horizontal_m * 1000 + hole + 2 * hole, abs=1e-3)
    assert box.size.Z == pytest.approx(2 * hole, abs=1e-3)  # plate thickness
    assert box.size.X > box.size.Y  # the large loop is the longer arm
    # centred on the mast axis
    assert box.center().X == pytest.approx(0, abs=1e-6) and box.center().Y == pytest.approx(
        0, abs=1e-6
    )


def _hole_faces(shape, diameter_mm, tol=1e-3):
    b3d = need_cad()
    faces = shape.faces().filter_by(b3d.GeomType.CYLINDER)
    return [f for f in faces if abs(f.bounding_box().size.X - diameter_mm) < tol]


def test_conductor_holes_are_at_plus_minus_d_over_2():
    need_cad()
    s = spreader()
    dims = s.qfh.dimensions
    faces = _hole_faces(s.build(), 3.2)
    centres = sorted(
        (round(f.bounding_box().center().X, 4), round(f.bounding_box().center().Y, 4))
        for f in faces
    )
    d1, d2 = dims.large.horizontal_m * 1000, dims.small.horizontal_m * 1000
    expected = sorted(
        [
            (round(d1 / 2, 4), 0.0),
            (round(-d1 / 2, 4), 0.0),
            (0.0, round(d2 / 2, 4)),
            (0.0, round(-d2 / 2, 4)),
        ]
    )
    assert np.array(centres) == pytest.approx(np.array(expected), abs=1e-3)


def test_clearance_changes_the_hole_diameters_in_the_shape():
    need_cad()
    for clearance, conductor, mast in ((0.2, 3.2, 26.2), (0.4, 3.4, 26.4), (0.0, 3.0, 26.0)):
        shape = spreader(print_settings={"clearance_mm": clearance}).build()
        assert len(_hole_faces(shape, conductor)) >= 4, clearance
        assert len(_hole_faces(shape, mast)) >= 1, clearance


def test_mast_diameter_changes_the_central_hole():
    need_cad()
    shape = spreader(mast_outer_diameter_mm=32).build()  # VP25-like
    assert len(_hole_faces(shape, 32.2)) >= 1


# --- STL / STEP export ----------------------------------------------------------------------


def read_binary_stl(path: Path) -> np.ndarray:
    data = path.read_bytes()
    count = struct.unpack("<I", data[80:84])[0]
    assert len(data) == 84 + 50 * count, "not a binary STL"
    record = np.dtype([("normal", "<3f4"), ("vertices", "<9f4"), ("attr", "<u2")])
    triangles = np.frombuffer(data, dtype=record, count=count, offset=84)["vertices"]
    return triangles.reshape(count, 3, 3).astype(float)


def is_watertight(triangles: np.ndarray) -> bool:
    """Every edge is shared by exactly two triangles (after merging identical vertices)."""
    vertices, inverse = np.unique(
        np.round(triangles.reshape(-1, 3), 4), axis=0, return_inverse=True
    )
    index = inverse.reshape(-1, 3)
    edges = np.concatenate([index[:, [0, 1]], index[:, [1, 2]], index[:, [2, 0]]])
    edges = np.sort(edges, axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return bool(np.all(counts == 2)) and len(vertices) > 0


def mesh_volume(triangles: np.ndarray) -> float:
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    return float(np.sum(np.einsum("ij,ij->i", a, np.cross(b, c))) / 6.0)


def test_exported_stl_is_a_closed_mesh_with_positive_volume(tmp_path):
    need_cad()
    s = spreader()
    stl, step = s.export(tmp_path, "spreader")
    assert stl.name == "spreader.stl" and step.name == "spreader.step"
    assert stl.stat().st_size > 1000 and step.stat().st_size > 1000
    assert step.read_text(encoding="utf-8", errors="replace").startswith("ISO-10303-21")
    triangles = read_binary_stl(stl)
    assert is_watertight(triangles)
    volume = mesh_volume(triangles)
    assert volume > 0
    assert volume == pytest.approx(s.build().volume, rel=0.01)  # mesh vs exact solid


def test_export_creates_the_output_directory(tmp_path):
    need_cad()
    out = tmp_path / "nested" / "parts"
    paths = spreader().export(out, "x")
    assert all(p.exists() for p in paths)


# --- CLI ---------------------------------------------------------------------------------------


def test_cli_parts_writes_stl_and_step(tmp_path, capsys):
    need_cad()
    out = tmp_path / "out"
    assert main(["parts", str(EXAMPLES / "qfh_137mhz.yaml"), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "qfh_spreader.stl" in printed and "qfh_spreader.step" in printed
    assert (out / "qfh_spreader.stl").exists() and (out / "qfh_spreader.step").exists()
    assert is_watertight(read_binary_stl(out / "qfh_spreader.stl"))


def test_cli_parts_options_reach_the_part(tmp_path):
    need_cad()
    design = str(EXAMPLES / "qfh_137mhz.yaml")
    volumes = {}
    for label, extra in (
        ("default", []),
        ("clearance", ["--clearance-mm", "0.5"]),
        ("mast", ["--mast-diameter-mm", "32"]),
    ):
        out = tmp_path / label
        assert main(["parts", design, "--out", str(out), *extra]) == 0
        volumes[label] = mesh_volume(read_binary_stl(out / "qfh_spreader.stl"))
    # Each option changes the part (hole sizes, and the arm and hub sizes that follow from them).
    assert all(v > 0 for v in volumes.values())
    assert volumes["clearance"] != pytest.approx(volumes["default"], rel=1e-3)
    assert volumes["mast"] != pytest.approx(volumes["default"], rel=1e-3)


def test_cli_parts_rejects_templates_without_parts(tmp_path, capsys):
    code = main(["parts", str(EXAMPLES / "dipole_145mhz.yaml"), "--out", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 2
    assert "部品未対応" in captured.err and "'dipole'" in captured.err
    assert captured.out == ""
    assert list(tmp_path.iterdir()) == []


def test_cli_parts_explains_the_missing_extra(monkeypatch, tmp_path, capsys):
    real_require = base.require
    monkeypatch.setattr(
        base,
        "require",
        lambda module, purpose, extra="gui": real_require("no_such_cad_module", purpose, extra),
    )
    code = main(["parts", str(EXAMPLES / "qfh_137mhz.yaml"), "--out", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 2
    assert "uv sync --extra cad" in captured.err
    assert captured.out == ""
