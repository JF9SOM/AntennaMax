"""3D-printable QFH supports: spreaders with grooves and clamp plates (build123d, extra `cad`).

Tests that build a shape are skipped when build123d is not installed.
"""

import struct
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from antennamax.cli.main import main
from antennamax.mech import base
from antennamax.mech.base import PrintSettings, to_mm
from antennamax.mech.fasteners import Fastener, standard_screw_length_mm
from antennamax.mech.qfh_parts import (
    DEFAULT_MAST_OUTER_DIAMETER_M,
    QfhClamp,
    QfhLowerSpreader,
    QfhPartSet,
    QfhUpperSpreader,
    part_rows,
)
from antennamax.templates.qfh import Qfh

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def qfh(f_mhz: float = 435.0) -> Qfh:
    bend = 15 if f_mhz < 200 else 5
    return Qfh(center_frequency_mhz=f_mhz, diameter_mm=3, bend_radius_mm=bend)


def parts(f_mhz: float = 435.0, **overrides) -> QfhPartSet:
    return QfhPartSet(qfh=qfh(f_mhz), **overrides)


def need_cad():
    return pytest.importorskip("build123d")


def parse_listing(out: str) -> list[tuple[str, str, int, float]]:
    """(part, site, quantity, distance from top [mm]) for every row of the printed table."""
    rows = []
    for line in out.splitlines():
        fields = line.split()
        if (
            len(fields) >= 5
            and fields[1] in ("upper", "lower_large", "lower_small")
            and fields[2].isdigit()
        ):
            rows.append((fields[0], fields[1], int(fields[2]), float(fields[3])))
    return rows


# --- derived dimensions (no CAD needed) ------------------------------------------------------


def test_groove_screw_and_nut_dimensions_follow_the_settings():
    s = parts()
    assert s.print_settings.clearance_m == pytest.approx(0.0002)  # default 0.2 mm
    assert s.groove_radius_m == pytest.approx(0.0016)  # (3 mm + 0.2 mm) / 2
    assert s.screw_hole_diameter_m == pytest.approx(0.0032)
    assert s.nut_pocket_across_flats_m == pytest.approx(0.0057)  # 5.5 mm + 0.2 mm
    assert s.nut_pocket_depth_m == pytest.approx(0.0026)  # 2.4 mm + 0.2 mm
    assert s.mast_hole_diameter_m == pytest.approx(DEFAULT_MAST_OUTER_DIAMETER_M + 0.0002)
    wide = parts(print_settings={"clearance_mm": 0.4})
    assert wide.groove_radius_m == pytest.approx(0.0017)
    assert wide.screw_hole_diameter_m == pytest.approx(0.0034)


def test_default_plate_dimensions_are_derived():
    s = parts()
    wall = 0.0012
    assert s.resolved_body_thickness_m == pytest.approx(0.0026 + 2 * wall)
    assert s.resolved_clamp_thickness_m == pytest.approx(0.0016 + 2 * wall)
    # The screws sit beside the groove, clear of it and of each other's nut pockets.
    assert s.screw_offset_m == pytest.approx(0.0016 + wall + 0.0057 / 2)
    assert s.resolved_arm_width_m == pytest.approx(2 * (s.screw_offset_m + 0.0057 / 2 + wall))
    custom = parts(arm_width_mm=25, body_thickness_mm=6, clamp_thickness_mm=5, hub_wall_mm=8)
    assert custom.resolved_arm_width_m == pytest.approx(0.025)
    assert custom.resolved_body_thickness_m == pytest.approx(0.006)
    assert custom.resolved_clamp_thickness_m == pytest.approx(0.005)
    assert custom.hub_diameter_m == pytest.approx(0.0262 + 0.016)


def test_part_list_counts_and_installation_heights():
    s = parts()
    dims = s.qfh.dimensions
    by_name = {i.name: i for i in s.instances()}
    assert list(by_name) == [
        "qfh_upper_spreader",
        "qfh_lower_spreader_large",
        "qfh_lower_spreader_small",
        "qfh_clamp_large",
        "qfh_clamp_small",
    ]
    assert [by_name[n].count for n in by_name] == [1, 1, 1, 4, 4]
    # Distance from the top of the antenna: the top spreader at 0, the bottom bars at the loop
    # heights (the loops are aligned at the top, so the small loop's bottom is H2 below it).
    assert by_name["qfh_upper_spreader"].distance_from_top_m == 0.0
    assert by_name["qfh_lower_spreader_large"].distance_from_top_m == pytest.approx(
        dims.large.height_m
    )
    assert by_name["qfh_lower_spreader_small"].distance_from_top_m == pytest.approx(
        dims.small.height_m
    )
    assert dims.large.height_m > dims.small.height_m > 0
    assert all(i.part.part_name == i.name for i in by_name.values())


def test_fastener_counts():
    s = parts()
    assert s.clamp_count == 8
    assert s.screw_count == 16 and s.nut_count == 16  # two M3 screws and nuts per clamp
    thickness = s.resolved_clamp_thickness_m + s.resolved_body_thickness_m
    assert s.min_screw_length_m == pytest.approx(thickness)
    assert s.screw_length_mm == standard_screw_length_mm(to_mm(thickness)) == 10
    assert Fastener().name == "M3"


def test_placements_match_the_installation_heights():
    s = parts()
    dims = s.qfh.dimensions
    placements = s.placements()
    assert len(placements) == 1 + 2 + 8  # one upper, two lower, eight clamps
    z = {p.name: p.position_mm[2] for p in placements if "spreader" in p.name}
    assert z["qfh_upper_spreader"] == 0.0
    assert z["qfh_lower_spreader_large"] == pytest.approx(-to_mm(dims.large.height_m))
    assert z["qfh_lower_spreader_small"] == pytest.approx(-to_mm(dims.small.height_m))
    # Four large clamps (two at the top, two on the lower large bar) and four small ones.
    large = [p for p in placements if p.name == "qfh_clamp_large"]
    small = [p for p in placements if p.name == "qfh_clamp_small"]
    assert len(large) == len(small) == 4
    assert sorted(round(p.position_mm[2], 3) for p in large)[0] == pytest.approx(
        -to_mm(dims.large.height_m), abs=1e-3
    )
    assert all(p.position_mm[1] == 0.0 for p in large)  # along x
    assert all(p.position_mm[0] == 0.0 and p.rotation_deg == 90.0 for p in small)  # along y


@pytest.mark.parametrize(
    "overrides",
    [
        {"mast_outer_diameter_mm": 500},  # no room for a clamp between the hub and Dc/2
        {"mast_outer_diameter_mm": 0},
        {"arm_width_mm": 5},  # too narrow for the screws and nuts
        {"body_thickness_mm": -1},
        {"print_settings": {"clearance_mm": -0.1}},
        {"print_settings": {"build_volume_m": (0.2, 0.2, 0)}},
        {"unknown": 1},
    ],
)
def test_invalid_parameters(overrides):
    with pytest.raises(ValidationError):
        parts(**overrides)


# --- build volume ---------------------------------------------------------------------------


def test_build_volume_check():
    settings = PrintSettings()
    assert settings.build_volume_m == (0.22, 0.22, 0.25)
    assert settings.check_fit("ok", (220.0, 100.0, 5.0)) is None
    assert settings.check_fit("rotated", (100.0, 220.0, 5.0)) is None  # either orientation
    problem = settings.check_fit("big", (289.7, 274.0, 5.0))
    assert problem is not None
    assert problem.excess_mm == pytest.approx((69.7, 54.0, 0.0))
    assert "'big'" in problem.message() and "length +69.7 mm" in problem.message()
    assert settings.check_fit("tall", (10, 10, 260)).excess_mm[2] == pytest.approx(10.0)


# --- shapes ---------------------------------------------------------------------------------


def sizes(s):
    return {i.name: i.part.size_mm() for i in s.instances()}


def test_part_sizes_match_dc_of_each_loop():
    need_cad()
    s = parts()
    dims = s.qfh.dimensions
    dc1, dc2 = (
        to_mm(dims.large.compensated_horizontal_m),
        to_mm(dims.small.compensated_horizontal_m),
    )
    hub = to_mm(s.hub_diameter_m)
    width = to_mm(s.resolved_arm_width_m)
    got = sizes(s)
    tb, tc = to_mm(s.resolved_body_thickness_m), to_mm(s.resolved_clamp_thickness_m)
    # The upper spreader spans Dc1 along x and Dc2 along y: grooves and arms stop at Dc/2.
    assert got["qfh_upper_spreader"] == pytest.approx((dc1, dc2, tb), abs=1e-3)
    assert got["qfh_lower_spreader_large"] == pytest.approx((dc1, max(hub, width), tb), abs=1e-3)
    assert got["qfh_lower_spreader_small"] == pytest.approx((max(hub, width), dc2, tb), abs=1e-3)
    # A clamp runs from the edge of the hub to Dc/2.
    assert got["qfh_clamp_large"] == pytest.approx((dc1 / 2 - hub / 2, width, tc), abs=1e-3)
    assert got["qfh_clamp_small"] == pytest.approx((dc2 / 2 - hub / 2, width, tc), abs=1e-3)


def test_clamp_and_groove_reach_exactly_dc_over_2():
    need_cad()
    s = parts()
    dims = s.qfh.dimensions
    for loop, loop_dims in (("large", dims.large), ("small", dims.small)):
        half = to_mm(loop_dims.compensated_horizontal_m) / 2
        clamp = s.clamp(loop).build()
        placed_max = to_mm(s.clamp_center_m(loop)) + clamp.bounding_box().size.X / 2
        assert placed_max == pytest.approx(half, abs=1e-3)  # outer end of the clamp at Dc/2
    # The groove runs the full length of the arms (to Dc/2) and nothing is cut beyond it.
    b3d = need_cad()
    body = s.upper().build()
    for axis_rot, half in (
        ((0, 90, 0), dims.large.compensated_horizontal_m * 500),
        ((90, 0, 0), dims.small.compensated_horizontal_m * 500),
    ):
        channel = b3d.Rot(*axis_rot) * b3d.Cylinder(1.5, 2 * half - 0.01)  # conductor, d = 3 mm
        assert (body & channel).volume == pytest.approx(0.0, abs=1e-6)


def _assembled_arm(s, loop="large"):
    """Spreader body and the clamp on its +x arm (or +y for the small loop), as placed."""
    b3d = need_cad()
    body = s.upper().build()
    clamp = s.clamp(loop).build()
    c = to_mm(s.clamp_center_m(loop))
    if loop == "large":
        return body, b3d.Pos(c, 0, 0) * clamp
    return body, b3d.Pos(0, c, 0) * (b3d.Rot(0, 0, 90) * clamp)


@pytest.mark.parametrize("loop", ["large", "small"])
def test_clamp_on_the_spreader_leaves_a_round_channel_of_conductor_plus_clearance(loop):
    b3d = need_cad()
    s = parts()
    body, clamp = _assembled_arm(s, loop)
    assembly = body + clamp
    c = to_mm(s.clamp_center_m(loop))
    length = to_mm(s.clamp_length_m(loop))
    rot = (0, 90, 0) if loop == "large" else (90, 0, 0)
    pos = (c, 0, 0) if loop == "large" else (0, c, 0)

    def cylinder(radius):  # along the arm, over the clamped stretch
        return b3d.Pos(*pos) * (b3d.Rot(*rot) * b3d.Cylinder(radius, length))

    conductor = 3.0 / 2  # mm
    channel = 3.2 / 2  # conductor + clearance
    # The conductor (d = 3 mm) passes the clamped stretch without touching either part...
    assert (assembly & cylinder(conductor)).volume == pytest.approx(0.0, abs=1e-6)
    # ...and so does anything up to the channel radius ...
    assert (assembly & cylinder(channel - 0.01)).volume == pytest.approx(0.0, abs=1e-6)
    # ...but not a slightly larger one: the channel is the circle of d + clearance.
    assert (assembly & cylinder(channel + 0.05)).volume > 1.0
    # With only the spreader (no clamp) the groove is open on top: a conductor-sized cylinder
    # offset upwards would collide with the clamp, so the clamp does cover the groove.
    covered = b3d.Pos(0, 0, conductor) * cylinder(conductor)
    assert (clamp & covered).volume > 1.0


def test_lower_groove_is_continuous_across_the_mast_hole():
    b3d = need_cad()
    s = parts()
    dims = s.qfh.dimensions
    bar = s.lower("large").build()
    half = to_mm(dims.large.compensated_horizontal_m) / 2
    conductor = b3d.Rot(0, 90, 0) * b3d.Cylinder(1.5, 2 * half - 0.01)
    assert (bar & conductor).volume == pytest.approx(0.0, abs=1e-6)  # end to end, over the hole
    # The mast hole is there too: a cylinder of the mast's outer diameter fits through the bar.
    mast = b3d.Cylinder(to_mm(s.mast_outer_diameter_m) / 2, 20)
    assert (bar & mast).volume == pytest.approx(0.0, abs=1e-6)


def test_screw_holes_and_nut_pockets_exist():
    b3d = need_cad()
    s = parts()
    for part in (s.upper(), s.lower("large"), s.lower("small")):
        shape = part.build()
        holes = [
            f
            for f in shape.faces().filter_by(b3d.GeomType.CYLINDER)
            if abs(f.bounding_box().size.X - 3.2) < 1e-3
        ]
        expected_screws = 8 if isinstance(part, QfhUpperSpreader) else 4
        assert len(holes) >= expected_screws, part.part_name
    clamp = s.clamp("large").build()
    assert (
        len(
            [
                f
                for f in clamp.faces().filter_by(b3d.GeomType.CYLINDER)
                if abs(f.bounding_box().size.X - 3.2) < 1e-3
            ]
        )
        >= 2
    )


def test_clearance_changes_the_channel_and_hole_sizes_in_the_shapes():
    b3d = need_cad()
    for clearance, hole in ((0.2, 3.2), (0.4, 3.4), (0.0, 3.0)):
        s = parts(print_settings={"clearance_mm": clearance})
        shape = s.clamp("large").build()
        faces = shape.faces().filter_by(b3d.GeomType.CYLINDER)
        assert any(abs(f.bounding_box().size.X - hole) < 1e-3 for f in faces), clearance


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


def test_every_exported_stl_is_a_closed_mesh_with_positive_volume(tmp_path):
    need_cad()
    s = parts()
    for instance in s.instances():
        stl, step = instance.part.export(tmp_path)
        assert stl.name == f"{instance.name}.stl" and step.name == f"{instance.name}.step"
        assert step.read_text(encoding="utf-8", errors="replace").startswith("ISO-10303-21")
        triangles = read_binary_stl(stl)
        assert is_watertight(triangles), instance.name
        volume = mesh_volume(triangles)
        assert volume > 0, instance.name
        assert volume == pytest.approx(instance.part.build().volume, rel=0.01), instance.name


def test_export_creates_the_output_directory(tmp_path):
    need_cad()
    paths = parts().upper().export(tmp_path / "nested" / "parts")
    assert all(p.exists() for p in paths)


# --- build volume with the real designs ----------------------------------------------------------


def test_435mhz_parts_fit_the_default_build_volume():
    need_cad()
    s = parts(435.0)
    assert [s.print_settings.check_fit(n, size) for n, size in sizes(s).items()] == [None] * 5


def test_137mhz_parts_exceed_the_build_volume():
    need_cad()
    s = parts(137.5)
    problems = {
        n: s.print_settings.check_fit(n, size)
        for n, size in sizes(s).items()
        if s.print_settings.check_fit(n, size)
    }
    assert set(problems) == {
        "qfh_upper_spreader",
        "qfh_lower_spreader_large",
        "qfh_lower_spreader_small",
    }  # the clamps (127 mm) fit
    assert problems["qfh_upper_spreader"].excess_mm[0] == pytest.approx(289.7 - 220.0, abs=0.1)


# --- CLI ---------------------------------------------------------------------------------------


def test_cli_parts_435mhz_lists_parts_without_warnings(tmp_path, capsys):
    need_cad()
    out = tmp_path / "out"
    assert main(["parts", str(EXAMPLES / "qfh_435mhz.yaml"), "--out", str(out)]) == 0
    captured = capsys.readouterr()
    assert "warning" not in captured.err
    for name in ("qfh_upper_spreader", "qfh_lower_spreader_large", "qfh_clamp_small"):
        assert name in captured.out
        assert (out / f"{name}.stl").exists() and (out / f"{name}.step").exists()
    assert "16 x M3 screws" in captured.out and "16 x M3 hex nuts" in captured.out
    assert "From top[mm]" in captured.out
    rows = parse_listing(captured.out)
    assert ("qfh_lower_spreader_large", "lower_large", 1, 229.8) in rows
    assert sum(q for n, _, q, _ in rows if n == "qfh_clamp_large") == 4
    for stl in out.glob("*.stl"):
        assert is_watertight(read_binary_stl(stl)), stl.name


def test_cli_parts_137mhz_warns_which_parts_exceed_the_build_volume(tmp_path, capsys):
    need_cad()
    design = str(EXAMPLES / "qfh_137mhz.yaml")
    assert main(["parts", design, "--out", str(tmp_path), "--support", "integrated"]) == 0
    err = capsys.readouterr().err
    assert err.count("antennamax: warning: part") == 3
    assert "'qfh_upper_spreader'" in err and "length +69.7 mm" in err
    assert "'qfh_lower_spreader_large'" in err and "'qfh_lower_spreader_small'" in err
    assert "qfh_clamp" not in err


def test_cli_build_volume_option(tmp_path, capsys):
    need_cad()
    design = str(EXAMPLES / "qfh_137mhz.yaml")
    assert (
        main(["parts", design, "--out", str(tmp_path), "--build-volume-mm", "300", "300", "250"])
        == 0
    )
    assert "warning" not in capsys.readouterr().err  # 289.7 x 274 now fits


def test_cli_parts_options_reach_the_part(tmp_path, capsys):
    need_cad()
    design = str(EXAMPLES / "qfh_435mhz.yaml")
    volumes = {}
    for label, extra in (
        ("default", []),
        ("clearance", ["--clearance-mm", "0.5"]),
        ("mast", ["--mast-diameter-mm", "32"]),
    ):
        out = tmp_path / label
        assert main(["parts", design, "--out", str(out), *extra]) == 0
        volumes[label] = mesh_volume(read_binary_stl(out / "qfh_upper_spreader.stl"))
    capsys.readouterr()
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
    code = main(["parts", str(EXAMPLES / "qfh_435mhz.yaml"), "--out", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 2
    assert "uv sync --extra cad" in captured.err
    assert captured.out == ""


def test_part_classes_are_exported():
    # The three part kinds are separate classes with their own meta information.
    assert QfhUpperSpreader(qfh=qfh()).distance_from_top_m == 0.0
    assert QfhLowerSpreader(qfh=qfh(), loop="small").distance_from_top_m == pytest.approx(
        qfh().dimensions.small.height_m
    )
    assert QfhClamp(qfh=qfh(), loop="large").part_name == "qfh_clamp_large"


# --- the listing: one row per kind and installation site -----------------------------------------


def test_listing_rows_of_the_integrated_set_follow_h1_h2():
    s = parts(435.0)
    dims = s.qfh.dimensions
    h1, h2 = dims.large.height_m, dims.small.height_m
    rows = [(r.name, r.site, r.count, r.distance_from_top_m) for r in part_rows_of(s)]
    assert rows == [
        ("qfh_upper_spreader", "upper", 1, 0.0),
        ("qfh_lower_spreader_large", "lower_large", 1, pytest.approx(h1)),
        ("qfh_lower_spreader_small", "lower_small", 1, pytest.approx(h2)),
        (
            "qfh_clamp_large",
            "upper",
            2,
            0.0,
        ),  # the large loop's clamps: two on the top spreader ...
        ("qfh_clamp_large", "lower_large", 2, pytest.approx(h1)),  # ... two on the lower bar
        ("qfh_clamp_small", "upper", 2, 0.0),
        ("qfh_clamp_small", "lower_small", 2, pytest.approx(h2)),
    ]


def part_rows_of(s):
    need_cad()
    return part_rows(s)


def test_listing_totals_match_the_part_list_and_the_fasteners():
    s = parts(435.0)
    rows = part_rows_of(s)
    for instance in s.instances():
        assert sum(r.count for r in rows if r.name == instance.name) == instance.count
    assert sum(r.count for r in rows) == 11
    assert s.screw_count == s.nut_count == 16  # unchanged by how the rows are grouped


def test_cli_listing_shows_the_sites_and_heights_of_the_integrated_parts(tmp_path, capsys):
    need_cad()
    assert main(["parts", str(EXAMPLES / "qfh_435mhz.yaml"), "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    dims = qfh(435.0).dimensions
    h1, h2 = round(to_mm(dims.large.height_m), 1), round(to_mm(dims.small.height_m), 1)
    assert parse_listing(out) == [
        ("qfh_upper_spreader", "upper", 1, 0.0),
        ("qfh_lower_spreader_large", "lower_large", 1, h1),
        ("qfh_lower_spreader_small", "lower_small", 1, h2),
        ("qfh_clamp_large", "upper", 2, 0.0),
        ("qfh_clamp_large", "lower_large", 2, h1),
        ("qfh_clamp_small", "upper", 2, 0.0),
        ("qfh_clamp_small", "lower_small", 2, h2),
    ]
    assert "Printed parts: 11 pieces" in out
    assert "-0.0" not in out


# --- sign of the distance from the top -----------------------------------------------------------


def test_listing_distance_never_shows_negative_zero_but_keeps_real_negatives():
    from antennamax.cli.main import _distance_mm

    def shown(distance_m):
        return f"{_distance_mm(distance_m):.1f}"

    assert shown(0.0) == "0.0" and shown(-0.0) == "0.0"
    assert shown(-1e-9) == "0.0" and shown(-0.00004) == "0.0"  # rounds to a negative zero
    assert shown(0.7266) == "726.6"
    assert shown(-0.0125) == "-12.5"  # above the top: stays negative
    assert shown(-0.0004) == "-0.4"


def test_placement_above_the_top_has_a_negative_distance():
    from antennamax.mech.qfh_parts import Placement

    above = Placement("x", QfhUpperSpreader(qfh=qfh()), (0.0, 0.0, 12.5), 0.0, "upper")
    below = Placement("x", QfhUpperSpreader(qfh=qfh()), (0.0, 0.0, -229.8), 0.0, "lower_large")
    assert above.distance_from_top_m == pytest.approx(-0.0125)
    assert below.distance_from_top_m == pytest.approx(0.2298)


def test_cli_listing_prints_a_part_above_the_top_with_a_minus_sign(monkeypatch, tmp_path, capsys):
    need_cad()
    from antennamax.mech import qfh_parts
    from antennamax.mech.qfh_parts import PartRow

    size = (10.0, 10.0, 5.0)
    rows = [
        PartRow("qfh_upper_spreader", "upper", 1, -0.0125, size),  # 12.5 mm above the top
        PartRow("qfh_clamp_large", "upper", 2, -0.00004, size),  # rounds to -0.0
        PartRow("qfh_clamp_small", "lower_small", 2, 0.2185, size),
    ]
    monkeypatch.setattr(qfh_parts, "part_rows", lambda part_set: rows)
    assert main(["parts", str(EXAMPLES / "qfh_435mhz.yaml"), "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert parse_listing(out) == [
        ("qfh_upper_spreader", "upper", 1, -12.5),
        ("qfh_clamp_large", "upper", 2, 0.0),
        ("qfh_clamp_small", "lower_small", 2, 218.5),
    ]
    assert "-12.5" in out and "-0.0" not in out
