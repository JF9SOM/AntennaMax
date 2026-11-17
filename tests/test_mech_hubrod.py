"""Hub-and-rod QFH supports (hubs, purchased rods, conductor fixtures) and the choice between
them and the integrated spreaders. Shape tests need build123d (extra `cad`)."""

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from antennamax.cli.main import main
from antennamax.mech.base import to_mm
from antennamax.mech.qfh_hubrod import QfhHub, QfhHubRodPartSet
from antennamax.mech.qfh_parts import QfhPartSet, part_rows
from antennamax.mech.qfh_support import plan_supports
from antennamax.templates.qfh import Qfh
from test_mech import is_watertight, mesh_volume, parse_listing, read_binary_stl

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


def test_auto_chooses_integrated_at_435mhz():
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
        "qfh_drill_guide_large",
        "qfh_drill_guide_small",
    ]
    # The spreaders and clamps of the integrated design (the hub is now a boss for the mast set
    # screws, 7.3 mm thick, and its wall a little thicker, which shortens the clamps).
    assert sizes["qfh_upper_spreader"] == pytest.approx((91.11, 86.15, 7.29), abs=0.05)
    assert sizes["qfh_clamp_large"] == pytest.approx((27.22, 19.4, 4.0), abs=0.05)
    assert sizes["qfh_drill_guide_large"] == pytest.approx((36.68, 36.68, 9.6), abs=0.05)


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
    assert list(by_name) == [
        "qfh_hub_upper",
        "qfh_hub_lower_large",
        "qfh_hub_lower_small",
        "qfh_fixture",
        "qfh_hub_clamp",
        "qfh_fixture_clamp",
        "qfh_drill_guide_large",
        "qfh_drill_guide_small",
    ]
    assert [by_name[n].count for n in by_name] == [1, 1, 1, 8, 8, 8, 1, 1]
    assert by_name["qfh_hub_upper"].distance_from_top_m == 0.0
    assert by_name["qfh_hub_lower_large"].distance_from_top_m == pytest.approx(dims.large.height_m)
    assert by_name["qfh_hub_lower_small"].distance_from_top_m == pytest.approx(dims.small.height_m)
    uses = {u.purpose: u for u in s.fasteners()}
    assert uses["hub clamp plates"].screws == 16  # two per clamp plate, eight plates
    assert uses["fixture clamp plates"].screws == 16
    assert uses["rod retention (hub)"].screws == 8  # one per rod socket: 4 + 2 + 2
    assert uses["rod fixing (fixture)"].screws == 8  # one per fixture
    assert uses["mast set screws"].screws == 6  # two in the mast hole of each hub
    assert uses["drill guide set screws"].screws == 2  # one in each drill guide collar
    assert s.clamp_count == 16
    assert s.screw_count == s.nut_count == 56
    thickness = s.resolved_clamp_thickness_m
    assert uses["hub clamp plates"].min_length_m == pytest.approx(thickness + s.hub_height_m)
    assert uses["fixture clamp plates"].min_length_m == pytest.approx(
        thickness + s.fixture_height_m
    )
    assert uses["hub clamp plates"].screw_length_mm == 20
    assert uses["rod retention (hub)"].screw_length_mm == 6


def test_placements_follow_the_installation_heights():
    s = hubrod()
    dims = s.qfh.dimensions
    placements = s.placements()
    assert len(placements) == 3 + 8 + 8 + 8 + 2  # hubs, three kinds of clamp/fixture, two guides
    hubs = {
        p.name: p.position_mm[2]
        for p in placements
        if p.name.startswith("qfh_hub_") and "clamp" not in p.name
    }
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
        {"groove_margin_mm": 0},
        {"groove_margin_mm": 30},  # no room left for the hub's clamp plates
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
    b3d = need_cad()
    s = hubrod()
    for kind, sockets in (("upper", 4), ("lower_large", 2), ("lower_small", 2)):
        hub = s.hub(kind)
        assert len(hub.directions_deg) == sockets
        shape = hub.build()
        cylinders = shape.faces().filter_by(b3d.GeomType.CYLINDER)
        rod_holes = [f for f in cylinders if abs(f.bounding_box().size.Z - 8.2) < 1e-3]
        assert len(rod_holes) >= sockets, kind
        screws = [
            f
            for f in cylinders
            if abs(f.bounding_box().size.X - 3.2) < 1e-3
            or abs(f.bounding_box().size.Y - 3.2) < 1e-3
        ]
        # per arm: one retaining screw for the rod and two for the clamp plate
        assert len(screws) >= 3 * sockets, kind
        size = shape.bounding_box().size
        assert size.X == pytest.approx(to_mm(2 * s.hub_radius_m), abs=1e-3)
        assert size.Z == pytest.approx(to_mm(s.hub_height_m), abs=1e-3)


def test_fixture_has_a_rod_screw_and_two_clamp_screws():
    b3d = need_cad()
    s = hubrod()
    shape = s.fixture().build()
    screws = [
        f
        for f in shape.faces().filter_by(b3d.GeomType.CYLINDER)
        if abs(f.bounding_box().size.X - 3.2) < 1e-3
    ]
    assert len(screws) >= 3  # one holds the fixture on the rod, two hold its clamp plate
    assert shape.bounding_box().size.Z == pytest.approx(to_mm(s.fixture_height_m), abs=1e-3)
    assert s.fixture_height_m == pytest.approx(s.hub_height_m)  # same rod axis, same bottom wall


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
    """Hub, hub clamp, rod, fixture and fixture clamp on the +x arm, as placed in the antenna."""
    b3d = need_cad()
    hub = s.hub("upper").build()
    hub_clamp = b3d.Pos(to_mm(s.hub_clamp_center_radius_m), 0, 0) * s.hub_clamp().build()
    c = to_mm(s.fixture_center_radius_m(loop))
    fixture = b3d.Pos(c, 0, 0) * s.fixture().build()
    clamp = b3d.Pos(c, 0, 0) * s.clamp().build()
    r0 = to_mm(s.hub_socket_bottom_radius_m)
    r1 = to_mm(s.fixture_socket_bottom_radius_m(loop))
    z = -to_mm(s.rod_axis_depth_m)
    rod = b3d.Pos((r0 + r1) / 2, 0, z) * (b3d.Rot(0, 90, 0) * b3d.Cylinder(4.0, r1 - r0))
    return hub, hub_clamp, fixture, clamp, rod


def _conductor(b3d, radius, x0, x1, dy=0.0, dz=0.0):
    """A cylinder along the arm axis from x0 to x1 (the conductor, or a gauge for the channel)."""
    return b3d.Pos((x0 + x1) / 2, dy, dz) * (b3d.Rot(0, 90, 0) * b3d.Cylinder(radius, x1 - x0))


@pytest.mark.parametrize("loop", ["large", "small"])
def test_conductor_is_clamped_in_a_round_channel_at_the_hub_and_at_the_fixture(loop):
    b3d = need_cad()
    s = hubrod()
    hub, hub_clamp, fixture, clamp, rod = _assembled_arm(s, loop)
    half = to_mm(s.loop_half_length_m(loop))  # Dc/2
    groove_in = to_mm(s.hub_groove_inner_radius_m)
    hub_out = to_mm(s.hub_clamp_outer_radius_m)
    fix_in = to_mm(s.fixture_inner_radius_m(loop))
    solids = {
        "hub": hub,
        "hub clamp": hub_clamp,
        "fixture": fixture,
        "fixture clamp": clamp,
        "rod": rod,
    }

    # The whole conductor, from the groove margin on the hub to Dc/2, touches no part.
    conductor = _conductor(b3d, 1.5, groove_in, half)
    for name, solid in solids.items():
        assert (solid & conductor).volume == pytest.approx(0.0, abs=1e-6), name

    # Two clamped stretches, each a round channel of d + clearance = 3.2 mm: a gauge up to the
    # channel radius passes, a slightly larger one hits the groove walls.
    for label, (x0, x1, lower, upper) in {
        "hub": (groove_in, hub_out, hub, hub_clamp),
        "fixture": (fix_in, half, fixture, clamp),
    }.items():
        both = lower + upper
        assert (both & _conductor(b3d, 1.6 - 0.01, x0, x1)).volume == pytest.approx(
            0.0, abs=1e-6
        ), label
        assert (both & _conductor(b3d, 1.6 + 0.05, x0, x1)).volume > 1.0, label
        # Sandwiched: the clamp lies above the conductor, the body below it.
        assert (upper & _conductor(b3d, 1.5, x0, x1, dz=1.5)).volume > 0.1, label
        assert (lower & _conductor(b3d, 1.5, x0, x1, dz=-1.5)).volume > 0.1, label
        assert (lower & _conductor(b3d, 1.5, x0, x1, dz=1.5)).volume == pytest.approx(
            0.0, abs=1e-6
        ), label
        # Centred on the arm axis: shifted sideways by 0.3 mm it touches the groove.
        assert (both & _conductor(b3d, 1.5, x0, x1, dy=0.3)).volume > 0.1, label

    # Between hub and fixture the conductor spans the exposed rod: nothing is there but the rod.
    gap = _conductor(b3d, 1.65, to_mm(s.hub_radius_m) + 0.01, fix_in - 0.01)
    for name in ("hub", "hub clamp", "fixture", "fixture clamp"):
        assert (solids[name] & gap).volume == pytest.approx(0.0, abs=1e-6), name
    # Towards the feed, inside the groove margin, the lowered top face leaves the conductor free.
    feed_side = _conductor(b3d, 1.5, 0.0, groove_in)
    assert (hub & feed_side).volume == pytest.approx(0.0, abs=1e-6)


def test_lower_hub_groove_runs_across_the_mast_hole():
    b3d = need_cad()
    s = hubrod()
    hub = s.hub("lower_large").build()
    clamps = [
        b3d.Pos(sign * to_mm(s.hub_clamp_center_radius_m), 0, 0)
        * (s.hub_clamp().build() if sign > 0 else b3d.Rot(0, 0, 180) * s.hub_clamp().build())
        for sign in (1, -1)
    ]
    radius = to_mm(s.hub_radius_m)
    conductor = _conductor(b3d, 1.5, -radius - 5, radius + 5)
    assert (hub & conductor).volume == pytest.approx(0.0, abs=1e-6)  # end to end, over the hole
    for clamp in clamps:
        assert (clamp & conductor).volume == pytest.approx(0.0, abs=1e-6)
        assert (hub & b3d.Pos(0, 0, 0) * _conductor(b3d, 1.6 + 0.05, -radius, radius)).volume > 1.0
    mast = b3d.Cylinder(to_mm(s.mast_outer_diameter_m) / 2, 40)
    assert (hub & mast).volume == pytest.approx(0.0, abs=1e-6)  # the mast passes through
    # The clamp plates leave the stretch around the mast hole open.
    inner = to_mm(s.hub_groove_inner_radius_m)
    assert clamps[0].bounding_box().min.X == pytest.approx(inner, abs=1e-3)
    assert clamps[1].bounding_box().max.X == pytest.approx(-inner, abs=1e-3)


def test_hub_clamp_dimensions():
    s = hubrod()
    wall = 0.0012
    assert s.hub_clamp_screw_offset_m == pytest.approx(
        0.0041 + wall + 0.0016
    )  # clear of the socket
    assert s.hub_clamp_width_m == pytest.approx(2 * (0.0069 + 0.00285 + wall))
    # The groove starts a margin outside the mast hole and the clamp ends where its corners
    # meet the rim of the hub.
    assert s.hub_groove_inner_radius_m == pytest.approx(0.0131 + 0.005)
    assert s.hub_clamp_outer_radius_m**2 + (s.hub_clamp_width_m / 2) ** 2 == pytest.approx(
        s.hub_radius_m**2
    )
    assert s.hub_clamp_length_m == pytest.approx(0.0182, abs=1e-4)
    wider = hubrod(groove_margin_mm=8)
    assert wider.hub_groove_inner_radius_m == pytest.approx(0.0131 + 0.008)
    assert wider.hub_clamp_length_m == pytest.approx(s.hub_clamp_length_m - 0.003)


def test_hub_clamp_screws_do_not_interfere_with_the_rod_retention_screw():
    b3d = need_cad()
    s = hubrod()
    wall = to_mm(s.wall_m)
    af = to_mm(s.nut_pocket_across_flats_m)
    hole_r = to_mm(s.screw_hole_diameter_m) / 2
    rod_r = to_mm(s.rod_hole_diameter_m) / 2
    offset = to_mm(s.hub_clamp_screw_offset_m)
    # Analytically: the nut pockets of the clamp screws and of the retaining screw are at least
    # a wall apart, and the clamp screw holes are at least a wall from the rod socket.
    assert (offset - af / 2) - af / 2 >= wall - 1e-9
    assert offset - hole_r - rod_r >= wall - 1e-9
    # In the shape: the material between them is there (probes inside the walls are solid).
    hub = s.hub("upper").build()
    height = to_mm(s.hub_height_m)
    pocket_depth = to_mm(s.nut_pocket_depth_m)
    cx = to_mm(s.hub_clamp_center_radius_m)
    rx = to_mm(s.retention_screw_radius_m)
    x0, x1 = min(cx, rx) - 2.0, max(cx, rx) + 2.0
    for sign in (1.0, -1.0):
        y_mid = sign * (af / 2 + wall / 2)  # the wall between the two pockets
        probe = b3d.Pos((x0 + x1) / 2, y_mid, -height + pocket_depth / 2) * b3d.Box(
            x1 - x0, wall * 0.5, pocket_depth * 0.8
        )
        assert (hub & probe).volume == pytest.approx(probe.volume, rel=1e-6)
        y_wall = sign * (rod_r + wall / 2 + 0.0)  # between a clamp screw hole and the socket
        probe2 = b3d.Pos(cx, y_wall, -to_mm(s.rod_axis_depth_m)) * b3d.Box(1.0, wall * 0.5, 4.0)
        assert (hub & probe2).volume == pytest.approx(probe2.volume, rel=1e-6)
        # The clamp screw hole itself is open all the way through the hub.
        hole = b3d.Pos(cx, sign * offset, -height / 2) * b3d.Cylinder(hole_r - 0.05, height)
        assert (hub & hole).volume == pytest.approx(0.0, abs=1e-6)


def test_wall_under_the_recess_edge_of_the_upper_hub_is_at_least_the_minimum_wall():
    b3d = need_cad()
    s = hubrod()
    wall = to_mm(s.wall_m)
    floor = -to_mm(s.groove_radius_m + 0.0001)  # floor of the recess: just below the groove
    socket_top = -to_mm(s.socket_top_depth_m)
    assert floor - socket_top >= wall - 1e-9  # analytically: at least the minimum wall
    hub = s.hub("upper").build()
    # Where the recess (radius = groove start) and the rod socket (starts at the hub's socket
    # bottom radius) overlap in plan, the wall between the recess floor and the socket top is
    # thinnest. The two overlap between these radii, on the arm axis:
    r_socket = to_mm(s.hub_socket_bottom_radius_m)
    r_recess = to_mm(s.hub_groove_inner_radius_m)
    assert r_socket < r_recess  # the zone exists, which is why this probe matters
    x_mid = (r_socket + r_recess) / 2

    def probe(thickness):  # a slab directly under the recess floor, over the socket
        z0 = floor - 0.01  # a hair below the floor surface
        return b3d.Pos(x_mid, 0, z0 - thickness / 2) * b3d.Box(0.05, 2.0, thickness)

    # A slab one minimum wall thick (less the hair) is solid ...
    slab = probe(wall - 0.02)
    assert (hub & slab).volume == pytest.approx(slab.volume, rel=1e-6)
    # ... and a slightly thicker one runs into the socket, so the wall is no thicker than that:
    # the probe really measures the wall.
    too_thick = probe(wall + 0.15)
    assert (hub & too_thick).volume < too_thick.volume * (1 - 1e-3)


def test_rod_fits_both_sockets_with_clearance_and_stays_in_them():
    b3d = need_cad()
    s = hubrod()
    hub, hub_clamp, fixture, clamp, rod = _assembled_arm(s)
    assert (hub & rod).volume == pytest.approx(0.0, abs=1e-6)
    assert (fixture & rod).volume == pytest.approx(0.0, abs=1e-6)
    # A rod shifted 0.25 mm along the arm would collide with the bottom of a socket.
    longer = b3d.Pos(0.25, 0, 0) * rod
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
        if placement.name == "qfh_hub_clamp":
            # on the hub: the plate's corners meet the rim, nothing sticks out
            assert extent == pytest.approx(to_mm(s.hub_clamp_outer_radius_m), abs=1e-3)
            assert extent <= to_mm(s.hub_radius_m)
        elif "drill_guide" in placement.name:  # on the mast, not on an arm
            assert extent == pytest.approx(to_mm(s.drill_guide_outer_diameter_m) / 2, abs=1e-3)
        elif "hub" in placement.name:
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
    assert (tmp_path / "qfh_fixture_clamp.step").exists() and (
        tmp_path / "qfh_hub_clamp.stl"
    ).exists()
    assert not (tmp_path / "qfh_upper_spreader.stl").exists()
    rods = [ln for ln in out.splitlines() if ln.strip().startswith("qfh_rod_")]
    assert len(rods) == 2 and "4 x 116.8 mm = 467.1 mm" in rods[0] and "4 x 108.9 mm" in rods[1]
    assert "total rod length 902.7 mm" in out or "total rod length 902.6 mm" in out
    assert "hub clamp plates: 16 x M3 screws" in out
    assert "fixture clamp plates: 16 x M3 screws" in out
    assert (
        "rod retention (hub): 8 x M3 screws" in out and "rod fixing (fixture): 8 x M3 screws" in out
    )
    assert "mast set screws: 6 x M3 screws" in out
    assert "drill guide set screws: 2 x M3 screws" in out
    assert "total: 56 x M3 screws, 56 x M3 hex nuts" in out
    rows = parse_listing(out)
    for kind in ("qfh_hub_clamp", "qfh_fixture_clamp"):
        assert sum(q for n, _, q, _ in rows if n == kind) == 8  # two kinds, eight of each
    assert ("qfh_hub_lower_large", "lower_large", 1, 726.6) in rows  # H1 from the top
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


# --- the listing: one row per kind and installation site -----------------------------------------


def test_listing_rows_of_the_hub_rod_set_follow_h1_h2():
    need_cad()
    s = hubrod()
    dims = s.qfh.dimensions
    h1, h2 = dims.large.height_m, dims.small.height_m
    rows = [(r.name, r.site, r.count, r.distance_from_top_m) for r in part_rows(s)]
    expected = [
        ("qfh_hub_upper", "upper", 1, 0.0),
        ("qfh_hub_lower_large", "lower_large", 1, pytest.approx(h1)),
        ("qfh_hub_lower_small", "lower_small", 1, pytest.approx(h2)),
    ]
    for kind in ("qfh_fixture", "qfh_hub_clamp", "qfh_fixture_clamp"):
        # four on the upper hub, two on each lower hub: at the top, H1 and H2 from the top
        expected += [
            (kind, "upper", 4, 0.0),
            (kind, "lower_large", 2, pytest.approx(h1)),
            (kind, "lower_small", 2, pytest.approx(h2)),
        ]
    expected += [  # the drill guides: the guide hole's distance from the top
        ("qfh_drill_guide_large", "lower_large", 1, pytest.approx(h1)),
        ("qfh_drill_guide_small", "lower_small", 1, pytest.approx(h2)),
    ]
    assert rows == expected


def test_hub_rod_listing_totals_match_the_part_list_and_the_fasteners():
    need_cad()
    s = hubrod()
    rows = part_rows(s)
    for instance in s.instances():
        assert sum(r.count for r in rows if r.name == instance.name) == instance.count
    assert sum(r.count for r in rows) == 29  # 27 hubs/fixtures/clamps + two drill guides
    assert s.screw_count == s.nut_count == 56  # 48 + 6 in the mast holes + 2 in the collars
    assert len(rows) == 14


def test_cli_listing_matches_the_dimensions_for_137mhz(tmp_path, capsys):
    need_cad()
    assert main(["parts", str(EXAMPLES / "qfh_137mhz.yaml"), "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    dims = qfh(137.5).dimensions
    h1, h2 = round(to_mm(dims.large.height_m), 1), round(to_mm(dims.small.height_m), 1)
    assert (h1, h2) == (726.6, 690.9)
    rows = parse_listing(out)
    assert len(rows) == 14 and sum(q for _, _, q, _ in rows) == 29
    for kind in ("qfh_fixture", "qfh_hub_clamp", "qfh_fixture_clamp"):
        assert [(s, q, d) for n, s, q, d in rows if n == kind] == [
            ("upper", 4, 0.0),
            ("lower_large", 2, h1),
            ("lower_small", 2, h2),
        ]
    assert "Printed parts: 29 pieces" in out
    assert "total: 56 x M3 screws, 56 x M3 hex nuts" in out
    assert "-0.0" not in out
