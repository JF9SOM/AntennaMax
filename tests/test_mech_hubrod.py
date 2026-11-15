"""Hub-and-rod QFH supports (hubs, purchased rods, conductor fixtures) and the choice between
them and the integrated spreaders. Shape tests need build123d (extra `cad`)."""

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from antennamax.cli.main import main
from antennamax.mech.base import to_mm
from antennamax.mech.qfh_hubrod import QfhHub, QfhHubRodPartSet
from antennamax.mech.qfh_parts import QfhPartSet
from antennamax.mech.qfh_support import plan_supports
from antennamax.templates.qfh import Qfh
from test_mech import is_watertight, mesh_volume, read_binary_stl

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def qfh(f_mhz: float) -> Qfh:
    bend = 15 if f_mhz < 200 else 5
    return Qfh(center_frequency_mhz=f_mhz, diameter_mm=3, bend_radius_mm=bend)


def hubrod(f_mhz: float = 137.5, **overrides) -> QfhHubRodPartSet:
    return QfhHubRodPartSet(qfh=qfh(f_mhz), **overrides)


def need_cad():
    return pytest.importorskip("build123d")


# --- choosing the support style ---------------------------------------------------------------


def test_auto_chooses_hub_rod_at_137mhz_and_everything_fits():
    need_cad()
    plan = plan_supports(qfh(137.5))
    assert plan.mode == "hub-rod" and isinstance(plan.part_set, QfhHubRodPartSet)
    assert "exceed the build volume" in plan.reason
    assert plan.part_set.fit_problems() == []  # every printed part is within 220 x 220 x 250 mm
    bed = plan.part_set.print_settings.build_volume_m
    for instance in plan.part_set.instances():
        size = instance.part.size_mm()
        assert max(size[:2]) <= to_mm(max(bed[:2])) and size[2] <= to_mm(bed[2]), instance.name


def test_auto_chooses_integrated_at_435mhz_with_the_same_parts_as_before():
    need_cad()
    plan = plan_supports(qfh(435.0))
    assert plan.mode == "integrated" and isinstance(plan.part_set, QfhPartSet)
    assert plan.reason == "all integrated parts fit the build volume"
    sizes = {i.name: i.part.size_mm() for i in plan.part_set.instances()}
    assert [i.name for i in plan.part_set.instances()] == [
        "qfh_upper_spreader",
        "qfh_lower_spreader_large",
        "qfh_lower_spreader_small",
        "qfh_clamp_large",
        "qfh_clamp_small",
    ]
    # Unchanged from the integrated design (see tests/test_mech.py and the earlier listing).
    assert sizes["qfh_upper_spreader"] == pytest.approx((91.1, 86.1, 5.0), abs=0.05)
    assert sizes["qfh_clamp_large"] == pytest.approx((27.7, 19.4, 4.0), abs=0.05)


def test_explicit_modes_override_auto():
    need_cad()
    assert plan_supports(qfh(137.5), "integrated").mode == "integrated"
    assert plan_supports(qfh(137.5), "hub-rod").mode == "hub-rod"
    # A big enough printer takes the integrated spreaders at 137.5 MHz as well.
    big = {"build_volume_m": (0.3, 0.3, 0.25)}
    assert plan_supports(qfh(137.5), print_settings=big).mode == "integrated"


def test_hub_rod_is_impossible_for_a_small_antenna_and_auto_falls_back():
    need_cad()
    with pytest.raises(ValidationError, match="too small for hubs and rods"):
        plan_supports(qfh(435.0), "hub-rod")
    tiny_bed = {"build_volume_m": (0.08, 0.08, 0.25)}  # nothing integrated fits
    plan = plan_supports(qfh(435.0), print_settings=tiny_bed)
    assert plan.mode == "integrated" and "hub-and-rod not possible" in plan.reason


def test_auto_uses_hub_rod_when_the_integrated_spreaders_cannot_be_built(monkeypatch):
    # With these dimensions hubs and rods need more room than the integrated arms, so the case
    # is forced: the integrated set refuses to build (a mast too wide for any clamp).
    from antennamax.mech import qfh_support

    def refuse(**kwargs):
        return QfhPartSet(**{**kwargs, "mast_outer_diameter_m": 0.5})  # raises ValidationError

    monkeypatch.setattr(qfh_support, "QfhPartSet", refuse)
    plan = plan_supports(qfh(137.5))
    assert plan.mode == "hub-rod"
    assert plan.reason.startswith(
        "integrated spreaders not possible: the large loop's arm is too short"
    )


# --- dimensions ---------------------------------------------------------------------------------


def test_rod_length_is_bottom_of_fixture_socket_minus_bottom_of_hub_socket():
    s = hubrod()
    dims = s.qfh.dimensions
    wall = 0.0012
    zone = 2 * (0.0057 / math.sqrt(3)) + 2 * wall  # clamp-screw stretch of the fixture
    hub_socket_bottom = 0.0262 / 2 + 4 * wall  # mast hole radius + hub wall
    for loop, loop_dims in (("large", dims.large), ("small", dims.small)):
        dc_half = loop_dims.compensated_horizontal_m / 2
        fixture_socket_bottom = dc_half - (wall + zone)  # fixture: socket, wall, screw stretch
        expected = fixture_socket_bottom - hub_socket_bottom
        assert s.rod_length_m(loop) == pytest.approx(expected, abs=1e-9)
    rods = {r.name: r for r in s.rods()}
    assert rods["qfh_rod_large"].count == 4 and rods["qfh_rod_small"].count == 4
    assert rods["qfh_rod_large"].length_m == pytest.approx(0.11677, abs=1e-5)
    assert rods["qfh_rod_small"].length_m == pytest.approx(0.10891, abs=1e-5)
    assert rods["qfh_rod_large"].length_m > rods["qfh_rod_small"].length_m
    total = sum(r.total_length_m for r in s.rods())
    assert total == pytest.approx(4 * s.rod_length_m("large") + 4 * s.rod_length_m("small"))


def test_insertion_depth_moves_both_sockets_and_leaves_the_rod_length_alone():
    shallow, deep = hubrod(rod_insert_depth_mm=15), hubrod(rod_insert_depth_mm=25)
    assert deep.hub_radius_m - shallow.hub_radius_m == pytest.approx(0.010)
    assert deep.fixture_length_m - shallow.fixture_length_m == pytest.approx(0.010)
    for loop in ("large", "small"):
        assert deep.rod_length_m(loop) == pytest.approx(shallow.rod_length_m(loop), abs=1e-9)


def test_hole_diameters_follow_the_rod_and_clearance():
    s = hubrod()
    assert s.rod_hole_diameter_m == pytest.approx(0.0082)  # 8 mm + 0.2 mm
    thin = hubrod(rod_diameter_mm=6, print_settings={"clearance_mm": 0.3})
    assert thin.rod_hole_diameter_m == pytest.approx(0.0063)


def test_part_list_counts_heights_and_fasteners():
    s = hubrod()
    dims = s.qfh.dimensions
    by_name = {i.name: i for i in s.instances()}
    assert [by_name[n].count for n in by_name] == [1, 1, 1, 8, 8]
    assert by_name["qfh_hub_upper"].distance_from_top_m == 0.0
    assert by_name["qfh_hub_lower_large"].distance_from_top_m == pytest.approx(dims.large.height_m)
    assert by_name["qfh_hub_lower_small"].distance_from_top_m == pytest.approx(dims.small.height_m)
    uses = {u.purpose: u for u in s.fasteners()}
    assert uses["clamp plates"].screws == 16  # two per clamp plate
    assert uses["rod retention"].screws == 8  # one per rod socket: 4 + 2 + 2
    assert s.screw_count == s.nut_count == 24
    assert uses["clamp plates"].min_length_m == pytest.approx(
        s.resolved_clamp_thickness_m + s.fixture_height_m
    )
    assert uses["clamp plates"].screw_length_mm == 20 and uses["rod retention"].screw_length_mm == 6


def test_placements_follow_the_installation_heights():
    s = hubrod()
    dims = s.qfh.dimensions
    placements = s.placements()
    assert len(placements) == 3 + 8 + 8  # hubs, fixtures, clamps
    hubs = {p.name: p.position_mm[2] for p in placements if "hub" in p.name}
    assert hubs["qfh_hub_upper"] == 0.0
    assert hubs["qfh_hub_lower_large"] == pytest.approx(-to_mm(dims.large.height_m))
    assert hubs["qfh_hub_lower_small"] == pytest.approx(-to_mm(dims.small.height_m))
    rods = s.rod_placements()
    assert len(rods) == 8
    for rod in rods:
        length = math.dist(rod.start_mm, rod.end_mm)
        loop = rod.name.rsplit("_", 1)[1]
        assert length == pytest.approx(to_mm(s.rod_length_m(loop)), abs=1e-9)
        assert rod.diameter_mm == pytest.approx(8.0)


@pytest.mark.parametrize(
    "overrides",
    [
        {"rod_diameter_mm": 0},
        {"rod_insert_depth_mm": -5},
        {"rod_insert_depth_mm": 300},  # the hub would be larger than the loop
        {"mast_outer_diameter_mm": 500},
        {"unknown": 1},
    ],
)
def test_invalid_parameters(overrides):
    with pytest.raises(ValidationError):
        hubrod(**overrides)


# --- shapes -------------------------------------------------------------------------------------


def _faces_of_diameter(shape, diameter_mm, tol=1e-3):
    b3d = need_cad()
    return [
        f
        for f in shape.faces().filter_by(b3d.GeomType.CYLINDER)
        if abs(f.bounding_box().size.Y - diameter_mm) < tol
        or abs(f.bounding_box().size.Z - diameter_mm) < tol
    ]


def test_hubs_have_the_right_number_of_rod_sockets_and_screws():
    need_cad()
    s = hubrod()
    for kind, sockets in (("upper", 4), ("lower_large", 2), ("lower_small", 2)):
        hub = s.hub(kind)
        assert len(hub.directions_deg) == sockets
        shape = hub.build()
        rod_holes = [
            f
            for f in shape.faces().filter_by(need_cad().GeomType.CYLINDER)
            if abs(f.bounding_box().size.Z - 8.2) < 1e-3
        ]
        assert len(rod_holes) >= sockets, kind
        screws = [
            f
            for f in shape.faces().filter_by(need_cad().GeomType.CYLINDER)
            if abs(f.bounding_box().size.X - 3.2) < 1e-3
        ]
        assert len(screws) >= sockets, kind  # one retaining screw hole per socket
        size = shape.bounding_box().size
        assert size.X == pytest.approx(to_mm(2 * s.hub_radius_m), abs=1e-3)
        assert size.Z == pytest.approx(to_mm(s.hub_height_m), abs=1e-3)


def test_rod_length_agrees_with_the_cad_sockets():
    b3d = need_cad()
    s = hubrod()
    hub_shape = s.hub("upper").build()
    # The +x socket of the hub: its cylindrical face spans from the bottom of the socket to the
    # outer surface of the hub.
    hub_faces = [
        f
        for f in hub_shape.faces().filter_by(b3d.GeomType.CYLINDER)
        if abs(f.bounding_box().size.Z - 8.2) < 1e-3
        and f.bounding_box().center().X > 0
        and abs(f.bounding_box().center().Y) < 1e-3
    ]
    assert hub_faces
    hub_bottom = min(f.bounding_box().min.X for f in hub_faces)
    fixture = s.fixture().build()
    fixture_faces = [
        f
        for f in fixture.faces().filter_by(b3d.GeomType.CYLINDER)
        if abs(f.bounding_box().size.Z - 8.2) < 1e-3
    ]
    assert fixture_faces
    socket_bottom_local = max(f.bounding_box().max.X for f in fixture_faces)
    centre = to_mm(s.fixture_center_radius_m("large"))
    rod_length = (centre + socket_bottom_local) - hub_bottom
    assert rod_length == pytest.approx(to_mm(s.rod_length_m("large")), abs=1e-3)


def _assembled_arm(s, loop="large"):
    """Hub, rod, fixture and clamp on the +x arm, as placed in the antenna."""
    b3d = need_cad()
    hub = s.hub("upper").build()
    fixture, clamp = s.fixture().build(), s.clamp().build()
    c = to_mm(s.fixture_center_radius_m(loop))
    r0 = to_mm(s.hub_socket_bottom_radius_m)
    r1 = to_mm(s.fixture_socket_bottom_radius_m(loop))
    z = -to_mm(s.rod_axis_depth_m)
    rod = b3d.Pos((r0 + r1) / 2, 0, z) * (b3d.Rot(0, 90, 0) * b3d.Cylinder(4.0, r1 - r0))
    return hub, b3d.Pos(c, 0, 0) * fixture, b3d.Pos(c, 0, 0) * clamp, rod


@pytest.mark.parametrize("loop", ["large", "small"])
def test_conductor_channel_runs_along_the_arm_to_dc_over_2(loop):
    b3d = need_cad()
    s = hubrod()
    hub, fixture, clamp, rod = _assembled_arm(s, loop)
    half = to_mm(s.loop_half_length_m(loop))  # Dc/2
    inner = to_mm(s.fixture_inner_radius_m(loop))

    # The groove and the clamp end at Dc/2; nothing is built beyond it (the conductor bends there).
    assert fixture.bounding_box().max.X == pytest.approx(half, abs=1e-3)
    assert clamp.bounding_box().max.X == pytest.approx(half, abs=1e-3)
    assert rod.bounding_box().max.X < half

    def conductor(radius):  # along the arm at y = 0, z = 0, over the whole fixture
        length = half - inner
        return b3d.Pos(inner + length / 2, 0, 0) * (
            b3d.Rot(0, 90, 0) * b3d.Cylinder(radius, length)
        )

    holder = fixture + clamp
    # The conductor (d = 3 mm) lies in the channel: no contact with the fixture, the clamp, the rod
    # (inserted in both sockets) or the hub, which the conductor passes over.
    for solid in (holder, rod, hub):
        assert (solid & conductor(1.5)).volume == pytest.approx(0.0, abs=1e-6)
    # The channel is the round hole of d + clearance = 3.2 mm: a slightly larger cylinder hits it.
    assert (holder & conductor(1.6 - 0.01)).volume == pytest.approx(0.0, abs=1e-6)
    assert (holder & conductor(1.6 + 0.05)).volume > 1.0
    # Its centre line is the arm axis: the same cylinder shifted sideways by 0.3 mm touches.
    shifted = b3d.Pos(0, 0.3, 0) * conductor(1.5)
    assert (holder & shifted).volume > 0.1


def test_rod_fits_both_sockets_with_clearance_and_stays_in_them():
    b3d = need_cad()
    s = hubrod()
    hub, fixture, clamp, rod = _assembled_arm(s)
    assert (hub & rod).volume == pytest.approx(0.0, abs=1e-6)
    assert (fixture & rod).volume == pytest.approx(0.0, abs=1e-6)
    # A rod 0.5 mm longer at either end would collide with the bottoms of the sockets.
    longer = b3d.Pos(0.25, 0, 0) * rod  # shifted: pushes into the fixture's socket bottom
    assert (fixture & longer).volume > 0.1 or (hub & longer).volume > 0.1


def test_no_printed_part_reaches_beyond_dc_over_2():
    b3d = need_cad()
    s = hubrod()
    dims = s.qfh.dimensions
    limits = {0.0: dims.large, 180.0: dims.large, 90.0: dims.small, 270.0: dims.small}
    for placement in s.placements():
        shape = placement.part.build()
        located = b3d.Pos(*placement.position_mm) * (b3d.Rot(0, 0, placement.rotation_deg) * shape)
        box = located.bounding_box()
        extent = max(abs(box.min.X), box.max.X, abs(box.min.Y), box.max.Y)
        if "hub" in placement.name:
            assert extent == pytest.approx(to_mm(s.hub_radius_m), abs=1e-3)
        else:
            loop_dims = limits[placement.rotation_deg]
            assert extent == pytest.approx(to_mm(loop_dims.compensated_horizontal_m / 2), abs=1e-3)


def test_every_hub_rod_part_exports_a_closed_mesh_with_positive_volume(tmp_path):
    need_cad()
    s = hubrod()
    for instance in s.instances():
        stl, step = instance.part.export(tmp_path)
        triangles = read_binary_stl(stl)
        assert is_watertight(triangles), instance.name
        volume = mesh_volume(triangles)
        assert volume > 0, instance.name
        assert volume == pytest.approx(instance.part.build().volume, rel=0.01), instance.name
        assert step.stat().st_size > 1000


def test_hub_classes_expose_their_meta_information():
    hub = QfhHub(qfh=qfh(137.5), kind="lower_small")
    assert hub.part_name == "qfh_hub_lower_small"
    assert hub.directions_deg == (90.0, 270.0)
    assert hub.distance_from_top_m == pytest.approx(qfh(137.5).dimensions.small.height_m)


# --- CLI ---------------------------------------------------------------------------------------


def test_cli_137mhz_uses_hub_rod_without_warnings_and_lists_everything(tmp_path, capsys):
    need_cad()
    assert main(["parts", str(EXAMPLES / "qfh_137mhz.yaml"), "--out", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert "warning" not in captured.err
    out = captured.out
    assert "Support: hub-rod (integrated parts exceed the build volume" in out
    for name in ("qfh_hub_upper", "qfh_hub_lower_large", "qfh_hub_lower_small", "qfh_fixture"):
        assert name in out and (tmp_path / f"{name}.stl").exists()
    assert (tmp_path / "qfh_fixture_clamp.step").exists()
    assert not (tmp_path / "qfh_upper_spreader.stl").exists()
    rods = [ln for ln in out.splitlines() if ln.strip().startswith("qfh_rod_")]
    assert len(rods) == 2 and "4 x 116.8 mm = 467.1 mm" in rods[0] and "4 x 108.9 mm" in rods[1]
    assert "total rod length 902.7 mm" in out or "total rod length 902.6 mm" in out
    assert "clamp plates: 16 x M3 screws" in out and "rod retention: 8 x M3 screws" in out
    assert "total: 24 x M3 screws, 24 x M3 hex nuts" in out
    line = next(ln for ln in out.splitlines() if ln.startswith("qfh_hub_lower_large"))
    assert float(line.split()[2]) == pytest.approx(726.6, abs=0.1)  # H1 from the top
    for stl in tmp_path.glob("*.stl"):
        assert is_watertight(read_binary_stl(stl)), stl.name


def test_cli_435mhz_still_uses_the_integrated_spreaders(tmp_path, capsys):
    need_cad()
    assert main(["parts", str(EXAMPLES / "qfh_435mhz.yaml"), "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Support: integrated (all integrated parts fit the build volume)" in out
    assert "Rods" not in out and (tmp_path / "qfh_upper_spreader.stl").exists()


def test_cli_support_option(tmp_path, capsys):
    need_cad()
    design = str(EXAMPLES / "qfh_137mhz.yaml")
    assert main(["parts", design, "--out", str(tmp_path / "a"), "--support", "integrated"]) == 0
    captured = capsys.readouterr()
    assert captured.err.count("warning") == 3 and "Support: integrated (requested)" in captured.out
    assert main(["parts", design, "--out", str(tmp_path / "b"), "--rod-diameter-mm", "10"]) == 0
    assert "Rods (not printed, 10 mm diameter)" in capsys.readouterr().out


def test_cli_hub_rod_on_a_small_antenna_is_an_error(tmp_path, capsys):
    need_cad()
    code = main(
        ["parts", str(EXAMPLES / "qfh_435mhz.yaml"), "--out", str(tmp_path), "--support", "hub-rod"]
    )
    captured = capsys.readouterr()
    assert code == 2 and "too small for hubs and rods" in captured.err
    assert captured.out == ""
