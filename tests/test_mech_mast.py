"""Mast fixing (M3 set screws in the mast hole) and the drill guide collars.

Shape tests need build123d (extra `cad`). Probes are thin slabs placed inside a wall: a slab of
(minimum wall - a little) must be solid, and a slab a little thicker than the wall must not be
(it runs into the neighbouring cavity or out of the part), so the probe really measures the wall.
"""

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from antennamax.cli.main import main
from antennamax.mech.base import to_mm
from antennamax.mech.qfh_hubrod import QfhHubRodPartSet
from antennamax.mech.qfh_parts import QfhDrillGuide, QfhPartSet
from antennamax.templates.qfh import Qfh
from test_mech import is_watertight, mesh_volume, parse_listing, read_binary_stl

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def qfh(f_mhz: float) -> Qfh:
    bend = 15 if f_mhz < 200 else 5
    return Qfh(center_frequency_mhz=f_mhz, diameter_mm=3, bend_radius_mm=bend)


def integrated(**overrides) -> QfhPartSet:
    return QfhPartSet(qfh=qfh(435.0), **overrides)


def hubrod(**overrides) -> QfhHubRodPartSet:
    return QfhHubRodPartSet(qfh=qfh(137.5), **overrides)


def need_cad():
    return pytest.importorskip("build123d")


# --- drill guide collars ---------------------------------------------------------------------


def _guide_hole_faces(shape):
    b3d = need_cad()
    return [
        f
        for f in shape.faces().filter_by(b3d.GeomType.CYLINDER)
        if sorted((f.bounding_box().size.X, f.bounding_box().size.Y, f.bounding_box().size.Z))[0]
        == pytest.approx(3.2, abs=1e-3)
        and f.bounding_box().size.Z < 3.3 + 1e-3 + 100  # any: filtered by the axis test below
    ]


def _axis_of(face):
    """The axis a guide-hole face runs along: the dimension of its bounding box that is long."""
    box = face.bounding_box()
    sizes = {"x": box.size.X, "y": box.size.Y, "z": box.size.Z}
    return max(sizes, key=sizes.get)


@pytest.mark.parametrize("make", [integrated, hubrod], ids=["integrated", "hub-rod"])
def test_guide_hole_heights_are_h1_and_h2_and_the_axes_are_90_degrees_apart(make):
    need_cad()
    s = make()
    dims = s.qfh.dimensions
    guides = {loop: s.drill_guide(loop) for loop in ("large", "small")}
    assert guides["large"].distance_from_top_m == pytest.approx(dims.large.height_m)
    assert guides["small"].distance_from_top_m == pytest.approx(dims.small.height_m)
    # Placed in the antenna, the centre of each guide hole is at -H (z = 0 is the top).
    placed = {p.name: p for p in s.placements() if "drill_guide" in p.name}
    assert placed["qfh_drill_guide_large"].position_mm[2] == pytest.approx(
        -to_mm(dims.large.height_m)
    )
    assert placed["qfh_drill_guide_small"].position_mm[2] == pytest.approx(
        -to_mm(dims.small.height_m)
    )
    axes = {}
    for loop, guide in guides.items():
        shape = guide.build()
        long_faces = [
            f
            for f in _guide_hole_faces(shape)
            if f.bounding_box().size.X > 4 or f.bounding_box().size.Y > 4
        ]
        assert len(long_faces) == 2  # one through each side of the collar wall
        assert {_axis_of(f) for f in long_faces} == {"x" if loop == "large" else "y"}
        axes[loop] = _axis_of(long_faces[0])
        for face in long_faces:  # the centre of the hole is at z = 0: H below the top
            assert face.bounding_box().center().Z == pytest.approx(0.0, abs=1e-6)
    assert axes == {"large": "x", "small": "y"}  # 90 degrees apart


def test_guide_hole_directions_match_the_lower_conductors_of_the_model():
    need_cad()
    s = hubrod()
    geometry = s.qfh.to_geometry()
    # The top conductor plane: where the feed wire starts (its other end is the feed gap above).
    top = geometry.wires[geometry.feeds[0].wire].start[2]
    per_loop = 1 + 2 * math.ceil(24 * 0.5) + 2
    for loop, wire, axis in (
        ("large", geometry.wires[0], (1.0, 0.0)),
        ("small", geometry.wires[per_loop], (0.0, 1.0)),
    ):
        # the first wire of each loop is its lower horizontal conductor, straight through the axis
        assert wire.start[2] == pytest.approx(wire.end[2])
        direction = (wire.end[0] - wire.start[0], wire.end[1] - wire.start[1])
        length = math.hypot(*direction)
        unit = (abs(direction[0] / length), abs(direction[1] / length))
        assert unit == pytest.approx(axis, abs=1e-9)  # parallel to the guide hole axis
        assert top - wire.start[2] == pytest.approx(s.drill_guide(loop).distance_from_top_m)


@pytest.mark.parametrize("loop", ["large", "small"])
def test_guide_hole_axis_passes_through_the_centre_of_the_mast(loop):
    b3d = need_cad()
    s = hubrod()
    guide = s.drill_guide(loop)
    shape = guide.build()
    rot = (0, 90, 0) if loop == "large" else (90, 0, 0)
    outer = to_mm(guide.drill_guide_outer_diameter_m) / 2

    def gauge(radius, dx=0.0, dy=0.0, dz=0.0):
        return b3d.Pos(dx, dy, dz) * (b3d.Rot(*rot) * b3d.Cylinder(radius, 2 * outer + 4))

    # A conductor-sized gauge along the axis of the hole, across the whole collar, is free ...
    assert (shape & gauge(1.5)).volume == pytest.approx(0.0, abs=1e-6)
    # ... a larger one hits the wall (the hole is d + clearance = 3.2 mm) ...
    assert (shape & gauge(1.65)).volume > 0.1
    # ... and the gauge shifted sideways or up by 0.3 mm touches it: the axis is the diameter of
    # the collar, so it goes through the centre of the mast.
    for shift in ((0.3, 0, 0), (0, 0.3, 0), (0, 0, 0.3)):
        shifted = gauge(1.5, *shift)
        if shift == (0.3, 0, 0) and loop == "large":
            continue  # shifting along its own axis changes nothing
        if shift == (0, 0.3, 0) and loop == "small":
            continue
        assert (shape & shifted).volume > 0.1
    # Both holes (on opposite sides of the mast) are on that one line.
    for face in (
        f
        for f in _guide_hole_faces(shape)
        if f.bounding_box().size.X > 4 or f.bounding_box().size.Y > 4
    ):
        c = face.bounding_box().center()
        off_axis = c.Y if loop == "large" else c.X
        assert off_axis == pytest.approx(0.0, abs=1e-6) and c.Z == pytest.approx(0.0, abs=1e-6)


def test_collar_dimensions_and_reference_dimension():
    s = hubrod()
    g = s.drill_guide("large")
    assert g.guide_hole_diameter_m == pytest.approx(0.0032)  # conductor + clearance
    # The wall is thick enough for the nut pocket of the collar's set screw: a wall beyond the
    # farthest corner of the pocket (a wall out from the mast hole, 2.6 mm deep).
    pocket_out = 0.0131 + 0.0012 + 0.0026
    wall = math.hypot(pocket_out, 0.00285) + 0.0012 - 0.0131
    assert g.resolved_drill_guide_wall_m == pytest.approx(wall)  # 5.24 mm
    assert g.drill_guide_outer_diameter_m == pytest.approx(0.0262 + 2 * wall)
    assert g.resolved_drill_guide_height_m == pytest.approx(3 * 0.0032)
    # The reference dimension: top face of the collar to the centre of the guide hole.
    assert g.guide_hole_below_top_m == pytest.approx(0.0048)
    assert g.collar_top_from_top_m == pytest.approx(g.distance_from_top_m - 0.0048)
    big = hubrod(drill_guide_height_mm=14, drill_guide_wall_mm=6)
    assert big.drill_guide("small").guide_hole_below_top_m == pytest.approx(0.007)
    with pytest.raises(ValidationError, match="too thin for the collar's set screw"):
        hubrod(drill_guide_wall_mm=4)
    with pytest.raises(ValidationError, match="drill_guide_height_m"):
        hubrod(drill_guide_height_mm=5)  # no room for the wall above the hole and the notch


def test_collar_bounding_box_and_its_top_face_above_the_hole_centre():
    need_cad()
    s = hubrod()
    for loop in ("large", "small"):
        g = s.drill_guide(loop)
        box = g.build().bounding_box()
        assert box.size.X == pytest.approx(to_mm(g.drill_guide_outer_diameter_m), abs=1e-3)
        assert box.size.Z == pytest.approx(to_mm(g.resolved_drill_guide_height_m), abs=1e-3)
        assert box.max.Z == pytest.approx(to_mm(g.guide_hole_below_top_m), abs=1e-6)  # 4.8 mm


@pytest.mark.parametrize("loop", ["large", "small"])
def test_orientation_notch_marks_the_plus_x_arm_direction(loop):
    b3d = need_cad()
    s = hubrod()
    g = s.drill_guide(loop)
    shape = g.build()
    inner = to_mm(g.mast_hole_diameter_m) / 2
    outer = to_mm(g.drill_guide_outer_diameter_m) / 2
    top = to_mm(g.guide_hole_below_top_m)
    depth = to_mm(g.drill_guide_notch_depth_m)
    wall = to_mm(g.wall_m)

    def probe(x, y, z0, z1, half_y=0.5):
        return b3d.Pos(x, y, (z0 + z1) / 2) * b3d.Box(1.0, 2 * half_y, z1 - z0)

    mid = (inner + outer) / 2
    # +x: the notch in the top face is empty ...
    notch = probe(mid, 0, top - depth + 0.05, top - 0.05)
    assert (shape & notch).volume == pytest.approx(0.0, abs=1e-6)
    # ... at -x, +y and -y the same place is solid.
    for x, y in ((-mid, 0), (0, mid), (0, -mid)):
        solid = probe(x, y, top - depth + 0.05, top - 0.05)
        if y:
            solid = b3d.Pos(x, y, (top - depth + top) / 2) * b3d.Box(
                1.0, 1.0, depth - 0.1
            )  # box oriented the same way: the notch is only at +x
        assert (shape & solid).volume == pytest.approx(solid.volume, rel=1e-6), (x, y)
    # Between the notch and the guide hole (large collar: the hole runs under the notch) there
    # is a full minimum wall.
    hole_top = to_mm(g.guide_hole_diameter_m) / 2
    slab = probe(mid, 0, hole_top + 0.01, hole_top + wall - 0.01, half_y=0.4)
    assert (shape & slab).volume == pytest.approx(slab.volume, rel=1e-6)
    thick = probe(mid, 0, hole_top + 0.01, hole_top + wall + 0.15, half_y=0.4)
    assert (shape & thick).volume < thick.volume * (1 - 1e-3)  # runs into the notch: wall = 1.2


# --- mast set screws -------------------------------------------------------------------------


def test_set_screw_counts_and_directions():
    s = hubrod()
    assert s.mast_screws_per_part == 2
    assert s.mast_screw_directions_deg == (45.0, 135.0)  # between the arms, 90 degrees apart
    assert s.mast_screw_count == 6  # two in each of the three hubs
    assert integrated().mast_screw_count == 6
    assert hubrod(mast_screws_per_part=1).mast_screw_directions_deg == (45.0,)
    assert hubrod(mast_screws_per_part=4).mast_screw_directions_deg == (45.0, 135.0, 225.0, 315.0)
    assert hubrod(mast_screws_per_part=4).mast_screw_count == 12
    for bad in (0, 5):
        with pytest.raises(ValidationError):
            hubrod(mast_screws_per_part=bad)


def test_integrated_hub_wall_and_boss_make_room_for_the_nut_pocket():
    s = integrated()
    wall = 0.0012
    # Pocket: a wall out from the mast hole, 2.6 mm deep; the hub rim is a wall beyond the farthest
    # corner of the pocket.
    outer = 0.0131 + wall + 0.0026
    assert s.mast_screw_nut_outer_radius_m == pytest.approx(outer)
    assert s.mast_screw_min_rim_radius_m == pytest.approx(math.hypot(outer, 0.00285) + wall)
    assert s.hub_diameter_m / 2 >= s.mast_screw_min_rim_radius_m - 1e-12
    # The hub is a boss: axis a wall below the top, corner of the pocket, a wall under it.
    assert s.mast_boss_thickness_m == pytest.approx(
        0.0016 + wall + 0.0057 / math.sqrt(3) + wall, abs=1e-9
    )
    assert s.mast_boss_thickness_m > s.resolved_body_thickness_m
    with pytest.raises(ValidationError, match="too thin for the mast set screws"):
        integrated(hub_wall_mm=3.5)
    assert s.mast_screw_min_length_m == pytest.approx(0.0026 + wall + 0.001)  # 4.8 mm


def _rotated_to_first_screw(part, angle=None):
    """The part turned so that a set screw (default: the first) points along +x."""
    b3d = need_cad()
    angle = part.mast_screw_directions_deg[0] if angle is None else angle
    return b3d.Rot(0, 0, -angle) * part.build()


def _wall_probes(part, axis_z):
    """Slab probes inside the walls around the first set screw (screw pointing along +x).

    Returns a list of (label, slab thickness probe builder results) as (probe, thicker probe or
    None): the thin probe must be solid; the thick one, if given, must not be.
    """
    b3d = need_cad()
    wall = to_mm(part.wall_m)
    mast_r = to_mm(part.mast_hole_diameter_m) / 2
    depth = to_mm(part.nut_pocket_depth_m)
    pocket_in = mast_r + wall
    pocket_out = pocket_in + depth
    screw_r = to_mm(part.screw_hole_diameter_m) / 2
    corner = to_mm(part.nut_pocket_circumradius_m)

    def slab(x0, x1, y0, y1, z0, z1):
        return b3d.Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * b3d.Box(
            x1 - x0, y1 - y0, z1 - z0
        )

    probes = {}
    # inner web: between the mast hole and the nut pocket, beside the screw hole
    probes["inner web"] = (
        slab(mast_r + 0.2, pocket_in - 0.02, 2.0, 2.6, axis_z - 0.5, axis_z + 0.5),
        slab(mast_r + 0.2, pocket_in + 0.15, 2.0, 2.6, axis_z - 0.5, axis_z + 0.5),
    )
    # outer web: behind the pocket, up to the rim
    probes["outer web"] = (
        slab(pocket_out + 0.01, pocket_out + wall - 0.02, 1.9, 2.8, axis_z - 0.5, axis_z + 0.5),
        slab(pocket_out + 0.01, pocket_out + wall + 0.25, 1.9, 2.8, axis_z - 0.5, axis_z + 0.5),
    )
    # under the pocket (its lower corner)
    low = axis_z - corner
    cx = (pocket_in + pocket_out) / 2
    probes["bottom wall"] = (
        slab(cx - 0.5, cx + 0.5, -0.3, 0.3, low - wall + 0.02, low - 0.01),
        slab(cx - 0.5, cx + 0.5, -0.3, 0.3, low - wall - 0.25, low - 0.01),
    )
    # over the screw hole, between the pocket and the rim (top wall)
    hole_top = axis_z + screw_r
    xs = (pocket_out + 0.3, pocket_out + 0.9)
    probes["top wall"] = (
        slab(xs[0], xs[1], -0.5, 0.5, hole_top + 0.01, hole_top + wall - 0.02),
        slab(xs[0], xs[1], -0.5, 0.5, hole_top + 0.01, hole_top + wall + 0.25),
    )
    return probes


def _check_walls(
    part, axis_z, sensitive=("inner web", "outer web", "bottom wall", "top wall"), angle=None
):
    shape = _rotated_to_first_screw(part, angle)
    for label, (thin, thick) in _wall_probes(part, axis_z).items():
        assert (shape & thin).volume == pytest.approx(thin.volume, rel=1e-6), label
        if label in sensitive:
            assert (shape & thick).volume < thick.volume * (1 - 1e-3), label  # measures the wall


def test_set_screw_walls_of_the_integrated_spreaders_are_at_least_the_minimum_wall():
    need_cad()
    s = integrated()
    axis = -to_mm(s.mast_screw_axis_depth_m)
    for part in (s.upper(), s.lower("large"), s.lower("small")):
        _check_walls(part, axis)


def test_set_screw_walls_of_the_hubs_are_at_least_the_minimum_wall():
    need_cad()
    s = hubrod()
    for kind in ("upper", "lower_large", "lower_small"):
        hub = s.hub(kind)
        # Mid-height in a thick hub: only the web between the mast hole and the pocket is tight;
        # the other probes (behind, above and below the pocket) just have to be solid.
        _check_walls(hub, -to_mm(s.hub_height_m) / 2, sensitive=("inner web",))


def _plan_clearance(part, pocket_xy, other_features):
    """Distance in plan between the set-screw pocket and other holes/pockets, less their radii."""
    pocket_radius = math.hypot(
        to_mm(part.nut_pocket_depth_m) / 2, to_mm(part.nut_pocket_across_flats_m) / 2
    )
    return min(math.dist(pocket_xy, (x, y)) - r - pocket_radius for x, y, r in other_features)


def test_set_screws_keep_a_wall_from_the_other_holes_and_pockets():
    s = hubrod()
    wall = to_mm(s.wall_m)
    pocket_r = to_mm(s.nut_pocket_circumradius_m)
    rod_r = to_mm(s.rod_hole_diameter_m) / 2
    cx = to_mm(s.hub_clamp_center_radius_m)
    offset = to_mm(s.hub_clamp_screw_offset_m)
    rx = to_mm(s.retention_screw_radius_m)
    bottom = to_mm(s.hub_socket_bottom_radius_m)
    # In plan, for the set screw at 45 degrees and the four arms of the upper hub (at 0, 90, 180,
    # 270): the clamp screw pockets, the retaining screw pockets and the start of the rod sockets.
    pocket_mid = to_mm(s.mast_screw_nut_inner_radius_m + s.nut_pocket_depth_m / 2)
    for angle in s.mast_screw_directions_deg:
        a = math.radians(angle)
        pocket_xy = (pocket_mid * math.cos(a), pocket_mid * math.sin(a))
        others = []
        for arm in (0.0, 90.0, 180.0, 270.0):
            u = (math.cos(math.radians(arm)), math.sin(math.radians(arm)))
            n = (-u[1], u[0])
            for side in (1.0, -1.0):
                others.append(
                    (cx * u[0] + side * offset * n[0], cx * u[1] + side * offset * n[1], pocket_r)
                )
            others.append((rx * u[0], rx * u[1], pocket_r))
            # the rod socket: modelled by points along its axis, from its bottom outwards
            for r in (bottom, bottom + 5, bottom + 10):
                others.append((r * u[0], r * u[1], rod_r))
        assert _plan_clearance(s.hub("upper"), pocket_xy, others) >= wall


# --- everything together -----------------------------------------------------------------------


@pytest.mark.parametrize("f_mhz", [137.5, 435.0])
def test_all_parts_with_set_screws_and_guides_are_closed_meshes_within_the_build_volume(
    f_mhz, tmp_path
):
    need_cad()
    from antennamax.mech.qfh_support import plan_supports

    plan = plan_supports(qfh(f_mhz))
    assert plan.mode == ("hub-rod" if f_mhz < 200 else "integrated")
    assert plan.part_set.fit_problems() == []  # every printed part within 220 x 220 x 250 mm
    names = [i.name for i in plan.part_set.instances()]
    assert "qfh_drill_guide_large" in names and "qfh_drill_guide_small" in names
    for instance in plan.part_set.instances():
        stl, _ = instance.part.export(tmp_path)
        triangles = read_binary_stl(stl)
        assert is_watertight(triangles), instance.name
        volume = mesh_volume(triangles)
        assert volume > 0, instance.name
        assert volume == pytest.approx(instance.part.build().volume, rel=0.01), instance.name


@pytest.mark.parametrize(
    ("example", "mode"), [("qfh_137mhz", "hub-rod"), ("qfh_435mhz", "integrated")]
)
def test_cli_lists_drill_guides_and_set_screws(example, mode, tmp_path, capsys):
    need_cad()
    assert main(["parts", str(EXAMPLES / f"{example}.yaml"), "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    dims = qfh(137.5 if "137" in example else 435.0).dimensions
    h1, h2 = round(to_mm(dims.large.height_m), 1), round(to_mm(dims.small.height_m), 1)
    rows = parse_listing(out)
    assert ("qfh_drill_guide_large", "lower_large", 1, h1) in rows
    assert ("qfh_drill_guide_small", "lower_small", 1, h2) in rows
    assert "Drill guides (collars on the mast; drill through both 3.2 mm guide holes):" in out
    # Both rows of the collar use the same reference as the table: From top.
    assert "From top = distance below the top conductor plane" in out
    assert "(From top = below the top conductor plane, the same reference as in the table)" in out
    for loop, h in (("large", h1), ("small", h2)):
        assert (
            f"{loop} loop: guide hole at {h:.1f} mm From top; "
            f"collar top face at {h - 4.8:.1f} mm From top"
        ) in out
    assert "(4.8 mm above the hole)" in out
    assert "notch faces the upper spreader's +x arm" in out
    assert "mast set screws: 6 x M3 screws (length >= 4.8 mm, use 6 mm), 6 x M3 hex nuts" in out
    assert "drill guide set screws: 2 x M3 screws (length >= 4.8 mm, use 6 mm)" in out
    assert "notch at +x in the bottom edge of the rim: the x axis is the large loop" in out
    assert (tmp_path / "qfh_drill_guide_large.stl").exists()
    assert (tmp_path / "qfh_drill_guide_small.step").exists()
    assert f"Support: {mode}" in out


def test_drill_guide_class_is_a_support_part():
    g = QfhDrillGuide(qfh=qfh(137.5), loop="small")
    assert g.part_name == "qfh_drill_guide_small"
    assert g.distance_from_top_m == pytest.approx(qfh(137.5).dimensions.small.height_m)


# --- the collar's own set screw ------------------------------------------------------------------


def test_collar_set_screw_walls_are_at_least_the_minimum_wall():
    need_cad()
    s = hubrod()
    for loop in ("large", "small"):
        collar = s.drill_guide(loop)
        assert collar.drill_guide_screw_direction_deg == 135.0
        # The screw is at the collar's mid-height, the same height as the guide hole. Behind the
        # pocket the wall is the collar rim; above and below there is more than a wall.
        _check_walls(
            collar,
            0.0,
            sensitive=("inner web", "outer web"),
            angle=collar.drill_guide_screw_direction_deg,
        )


@pytest.mark.parametrize("loop", ["large", "small"])
def test_collar_set_screw_keeps_clear_of_the_guide_hole_and_the_notch(loop):
    b3d = need_cad()
    s = hubrod()
    g = s.drill_guide(loop)
    wall = to_mm(g.wall_m)
    angle = math.radians(g.drill_guide_screw_direction_deg)
    pocket_mid = to_mm(g.mast_screw_nut_inner_radius_m + g.nut_pocket_depth_m / 2)
    px, py = pocket_mid * math.cos(angle), pocket_mid * math.sin(angle)
    pocket_radius = math.hypot(
        to_mm(g.nut_pocket_depth_m) / 2, to_mm(g.nut_pocket_across_flats_m) / 2
    )
    hole_r = to_mm(g.guide_hole_diameter_m) / 2
    # Distance from the pocket to the guide hole's axis (the x axis for the large collar, the y
    # axis for the small one), less both radii: a full wall or more.
    to_axis = abs(py) if loop == "large" else abs(px)
    assert to_axis - pocket_radius - hole_r >= wall
    # And from the notch at +x (angle 0): the pocket is 135 degrees away.
    notch_x = to_mm(g.drill_guide_outer_diameter_m) / 2
    assert math.dist((px, py), (notch_x, 0.0)) - pocket_radius - 3.0 >= wall
    # In the shape: the guide hole is still free from side to side, and the notch still empty.
    shape = g.build()
    outer = to_mm(g.drill_guide_outer_diameter_m) / 2
    rot = (0, 90, 0) if loop == "large" else (90, 0, 0)
    gauge = b3d.Rot(*rot) * b3d.Cylinder(1.5, 2 * outer + 4)
    assert (shape & gauge).volume == pytest.approx(0.0, abs=1e-6)
    # Mast hole of the collar: the mast fits, so does the screw's tip path (hole to the rim).
    mast = b3d.Cylinder(to_mm(g.mast_outer_diameter_m) / 2, 30)
    assert (shape & mast).volume == pytest.approx(0.0, abs=1e-6)


def test_collar_has_one_set_screw_each():
    s = hubrod()
    uses = {u.purpose: u for u in s.fasteners()}
    assert uses["drill guide set screws"].screws == 2  # one per collar
    assert uses["drill guide set screws"].min_length_m == pytest.approx(0.0048)
    assert integrated().fasteners()[-1].purpose == "drill guide set screws"


# --- orientation marks on the hubs and spreaders -------------------------------


def _marks():
    """(label, part, rim radius, bottom z, sockets on the +x axis?) for every marked part."""
    from antennamax.mech.qfh_parts import ORIENTATION_NOTCH_DEPTH_MM  # noqa: F401

    out = []
    s = integrated()
    boss = -to_mm(s.mast_boss_thickness_m)
    rim = to_mm(s.hub_diameter_m) / 2
    for part in (s.upper(), s.lower("large"), s.lower("small")):
        out.append((f"integrated {part.part_name}", part, rim, boss, False))
    h = hubrod()
    rim = to_mm(h.hub_radius_m)
    bottom = -to_mm(h.hub_height_m)
    for kind in ("upper", "lower_large", "lower_small"):
        hub = h.hub(kind)
        out.append((f"hub {kind}", hub, rim, bottom, 0.0 in hub.directions_deg))
    return out


@pytest.mark.parametrize("index", range(6))
def test_orientation_notch_at_plus_x_on_every_hub_and_spreader(index):
    b3d = need_cad()
    from antennamax.mech.qfh_parts import (
        NOTCH_WIDTH_MM,
        ORIENTATION_NOTCH_DEPTH_MM,
        ORIENTATION_NOTCH_HEIGHT_MM,
    )

    label, part, rim, bottom, socket_on_x = _marks()[index]
    shape = part.build()
    depth, height = ORIENTATION_NOTCH_DEPTH_MM, ORIENTATION_NOTCH_HEIGHT_MM
    wall = to_mm(part.wall_m)

    def box(cx, cy, z0, z1):
        return b3d.Pos(cx, cy, (z0 + z1) / 2) * b3d.Box(depth - 0.3, NOTCH_WIDTH_MM - 1.0, z1 - z0)

    z0, z1 = bottom + 0.1, bottom + height - 0.1
    mid = rim - depth / 2
    # +x: the notch is empty (the same width as the drill guide's notch) ...
    assert (shape & box(mid, 0.0, z0, z1)).volume == pytest.approx(0.0, abs=1e-6), label
    # ... at -x, +y and -y the same place in the rim is solid.
    for cx, cy in ((-mid, 0.0), (0.0, mid), (0.0, -mid)):
        probe = b3d.Pos(cx, cy, (z0 + z1) / 2) * b3d.Box(0.8, 0.8, z1 - z0)
        assert (shape & probe).volume == pytest.approx(probe.volume, rel=1e-6), (label, cx, cy)
    # Radially, a full wall remains between the notch and the mast hole ...
    assert rim - depth - to_mm(part.mast_hole_diameter_m) / 2 >= wall, label
    # ... and the walls above the notch are full where something lies above it: the socket bore
    # of a hub that has a socket on the x axis (a probe one wall thick is solid, a thicker one
    # runs into the bore).
    top = bottom + height
    slab = b3d.Pos(mid, 0, top + (wall - 0.02) / 2) * b3d.Box(1.0, 1.0, wall - 0.02)
    assert (shape & slab).volume == pytest.approx(slab.volume, rel=1e-6), label
    if socket_on_x:
        bore_bottom = -to_mm(part.rod_axis_depth_m) - to_mm(part.rod_hole_diameter_m) / 2
        assert bore_bottom - top >= wall - 1e-9, label
        thick = b3d.Pos(mid, 0, top + (bore_bottom - top + 0.3) / 2) * b3d.Box(
            1.0, 1.0, bore_bottom - top + 0.3
        )
        assert (shape & thick).volume < thick.volume * (1 - 1e-3), label  # measures that wall


def test_the_mark_identifies_the_large_loop_sockets_of_the_hubs():
    h = hubrod()
    # The notch is at +x. The upper hub and the large lower hub have sockets on the x axis (0 and
    # 180 degrees): those are the large loop's. The small lower hub has its sockets at 90 / 270
    # degrees, 90 degrees from the mark, like the small drill guide's hole.
    assert 0.0 in h.hub("upper").directions_deg and 180.0 in h.hub("upper").directions_deg
    assert h.hub("lower_large").directions_deg == (0.0, 180.0)
    assert h.hub("lower_small").directions_deg == (90.0, 270.0)
    # Upper hub: x sockets are the large loop's, y sockets the small loop's.
    assert {loop for _, loop, angle in h._arms() if angle in (0.0, 180.0) and _ == "upper"} == {
        "large"
    }
    assert {loop for _, loop, angle in h._arms() if angle in (90.0, 270.0) and _ == "upper"} == {
        "small"
    }
