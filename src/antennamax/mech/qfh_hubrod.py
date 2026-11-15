"""QFH supports for large antennas: hubs, purchased rods and conductor fixtures.

When the integrated spreaders (qfh_parts.py) are larger than the printer's build volume, the
supports are split: small printed hubs sit on the mast, insulating rods (for example fibreglass)
run out from the hubs, and a printed conductor fixture on the tip of each rod carries the groove
and clamp plate. The rod is not printed: its length is computed and listed.

  hub (upper x1, lower x2)  disc with the mast hole and rod sockets (upper: four directions,
                            lower: two), one M3 retaining screw per socket with its nut in a
                            pocket in the underside of the hub
  fixture (x8)              block with a rod socket at its inner end and, on its top, the
                            half-round conductor groove, running out to Dc/2
  fixture clamp (x8)        clamp plate over the groove, held by two M3 screws with captive nuts
                            (the same groove, clamp and screw scheme as the integrated parts)
  rods (not printed)        large-loop and small-loop rods; length = (position of the bottom of
                            the fixture's socket) - (position of the bottom of the hub's socket)

Vertical layout (millimetres, z = 0 is the conductor plane, as in the integrated parts): the
rod axes lie below the conductor plane; the hub's top is just under the conductor so that the
conductor passes over it; the fixture's top is the conductor plane, where the groove is cut.

TODO(要確認): 棒の径 8 mm(既定)は入手しやすい径の仮置き。差し込み深さ 20 mm・棒と固定具の接着
(固定具側に抜け止めのねじはない)・強度・たわみは未検証。
TODO(要確認): 抜け止めねじ(下面のナットに通し、先端で棒を押す)の長さと、棒を押さえる力は未検証。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import PositiveFloat, model_validator

from antennamax.mech.base import FitProblem, require_cad, to_mm
from antennamax.mech.qfh_parts import (
    FastenerUse,
    Loop,
    PartInstance,
    Placement,
    QfhSupportPart,
    Rod,
    _groove,
    _hex_prism,
)

DEFAULT_ROD_DIAMETER_M = 0.008  # a commonly available size; provisional
DEFAULT_ROD_INSERT_DEPTH_M = 0.020
RETENTION_SCREW_PROTRUSION_M = 1.0e-3  # how far the retaining screw reaches into the socket
MIN_EXPOSED_RODS_FACTOR = 1.0  # exposed rod length, in rod diameters, at the least

HubKind = Literal["upper", "lower_large", "lower_small"]
_HUB_DIRECTIONS = {
    "upper": (0.0, 90.0, 180.0, 270.0),
    "lower_large": (0.0, 180.0),
    "lower_small": (90.0, 270.0),
}


class QfhHubRodPart(QfhSupportPart):
    """Dimensions shared by the hub-and-rod parts."""

    rod_diameter_m: PositiveFloat = DEFAULT_ROD_DIAMETER_M
    rod_insert_depth_m: PositiveFloat = DEFAULT_ROD_INSERT_DEPTH_M

    # --- vertical layout (distances below the conductor plane) -----------------------------

    @property
    def rod_hole_diameter_m(self) -> float:
        return self.print_settings.hole_diameter_m(self.rod_diameter_m)

    @property
    def socket_top_depth_m(self) -> float:
        """Top of a rod socket: below the groove (or the conductor) with a wall in between."""
        return self.groove_radius_m + self.wall_m

    @property
    def rod_axis_depth_m(self) -> float:
        return self.socket_top_depth_m + self.rod_hole_diameter_m / 2.0

    @property
    def fixture_height_m(self) -> float:
        return self.socket_top_depth_m + self.rod_hole_diameter_m + self.wall_m

    @property
    def hub_top_depth_m(self) -> float:
        """The hub stays just below the conductor, which passes over it."""
        return self.groove_radius_m

    @property
    def retention_bottom_wall_m(self) -> float:
        """Below the socket: the retaining screw's nut pocket and a wall."""
        return self.nut_pocket_depth_m + self.wall_m

    @property
    def hub_bottom_depth_m(self) -> float:
        return self.socket_top_depth_m + self.rod_hole_diameter_m + self.retention_bottom_wall_m

    @property
    def hub_height_m(self) -> float:
        return self.hub_bottom_depth_m - self.hub_top_depth_m

    # --- along the arms ----------------------------------------------------------------------

    @property
    def hub_radius_m(self) -> float:
        wall = self.hub_wall_m or 4.0 * self.wall_m
        return self.mast_hole_diameter_m / 2.0 + wall + self.rod_insert_depth_m

    @property
    def hub_socket_bottom_radius_m(self) -> float:
        return self.hub_radius_m - self.rod_insert_depth_m

    @property
    def fixture_zone_m(self) -> float:
        """The stretch of the fixture beyond the socket that holds the clamp screws."""
        return 2.0 * self.nut_pocket_circumradius_m + 2.0 * self.wall_m

    @property
    def fixture_length_m(self) -> float:
        return self.rod_insert_depth_m + self.wall_m + self.fixture_zone_m

    @property
    def fixture_screw_axial_m(self) -> float:
        """Position of the clamp screws along the fixture, from its centre towards the outer end."""
        return self.fixture_length_m / 2.0 - self.fixture_zone_m / 2.0

    def fixture_inner_radius_m(self, loop: Loop) -> float:
        return self.loop_half_length_m(loop) - self.fixture_length_m

    def fixture_center_radius_m(self, loop: Loop) -> float:
        return self.loop_half_length_m(loop) - self.fixture_length_m / 2.0

    def fixture_socket_bottom_radius_m(self, loop: Loop) -> float:
        return self.fixture_inner_radius_m(loop) + self.rod_insert_depth_m

    def rod_length_m(self, loop: Loop) -> float:
        """(bottom of the fixture's socket) - (bottom of the hub's socket)."""
        return self.fixture_socket_bottom_radius_m(loop) - self.hub_socket_bottom_radius_m

    @property
    def retention_screw_min_length_m(self) -> float:
        return self.retention_bottom_wall_m + RETENTION_SCREW_PROTRUSION_M

    @model_validator(mode="after")
    def _check_rods(self) -> QfhHubRodPart:
        minimum = MIN_EXPOSED_RODS_FACTOR * self.rod_diameter_m
        for loop in ("large", "small"):
            exposed = self.fixture_inner_radius_m(loop) - self.hub_radius_m
            if exposed < minimum:
                raise ValueError(
                    f"the {loop} loop is too small for hubs and rods: {to_mm(exposed):.1f} mm "
                    f"of rod between hub and fixture, at least {to_mm(minimum):.1f} mm needed "
                    "(use the integrated spreaders, a smaller mast or a shallower insertion)"
                )
        return self


def _screw_cut(
    b: Any,
    x: float,
    y: float,
    z_bottom: float,
    z_top: float,
    screw_r: float,
    pocket_r: float,
    depth: float,
) -> Any:
    """A vertical screw hole from the bottom to the top with a nut pocket in the bottom face."""
    height = z_top - z_bottom + 2.0
    hole = b.Pos(0, 0, (z_top + z_bottom) / 2.0) * b.Cylinder(screw_r, height)
    pocket = b.Pos(0, 0, z_bottom) * _hex_prism(b, pocket_r, depth)
    return b.Pos(x, y, 0) * (hole + pocket)


class QfhHub(QfhHubRodPart):
    """Hub on the mast with rod sockets (upper: four directions, lower: two)."""

    kind: HubKind

    @property
    def part_name(self) -> str:
        return f"qfh_hub_{self.kind}"

    @property
    def directions_deg(self) -> tuple[float, ...]:
        return _HUB_DIRECTIONS[self.kind]

    @property
    def distance_from_top_m(self) -> float:
        dims = self.qfh.dimensions
        if self.kind == "upper":
            return 0.0
        return (dims.large if self.kind == "lower_large" else dims.small).height_m

    def build(self) -> Any:
        b = require_cad()
        top = -to_mm(self.hub_top_depth_m)
        bottom = -to_mm(self.hub_bottom_depth_m)
        radius = to_mm(self.hub_radius_m)
        mast_r = to_mm(self.mast_hole_diameter_m) / 2.0
        rod_r = to_mm(self.rod_hole_diameter_m) / 2.0
        axis_z = -to_mm(self.rod_axis_depth_m)
        socket_bottom = to_mm(self.hub_socket_bottom_radius_m)
        screw_r = to_mm(self.screw_hole_diameter_m) / 2.0
        pocket_r = to_mm(self.nut_pocket_circumradius_m)
        pocket_depth = to_mm(self.nut_pocket_depth_m)

        hub = b.Pos(0, 0, (top + bottom) / 2.0) * b.Cylinder(radius, top - bottom)
        hub = hub - b.Pos(0, 0, (top + bottom) / 2.0) * b.Cylinder(mast_r, 2.0 * (top - bottom))
        socket_length = radius + 1.0 - socket_bottom
        screw_radius = (socket_bottom + radius) / 2.0  # the middle of the inserted stretch
        for angle in self.directions_deg:
            bore = b.Pos((socket_bottom + radius + 1.0) / 2.0, 0, axis_z) * (
                b.Rot(0, 90, 0) * b.Cylinder(rod_r, socket_length)
            )
            screw = _screw_cut(
                b, screw_radius, 0.0, bottom, axis_z, screw_r, pocket_r, pocket_depth
            )
            hub = hub - b.Rot(0, 0, angle) * (bore + screw)
        return hub


class QfhFixture(QfhHubRodPart):
    """Block on a rod's tip: a rod socket at the inner end, the conductor groove on top.

    Modelled along +x with the socket end at -x; the groove runs the full length to the outer
    end, which sits at Dc/2 in the antenna.
    """

    @property
    def part_name(self) -> str:
        return "qfh_fixture"

    def build(self) -> Any:
        b = require_cad()
        length = to_mm(self.fixture_length_m)
        width = to_mm(self.resolved_arm_width_m)
        height = to_mm(self.fixture_height_m)
        rod_r = to_mm(self.rod_hole_diameter_m) / 2.0
        axis_z = -to_mm(self.rod_axis_depth_m)
        depth = to_mm(self.rod_insert_depth_m)
        screw_r = to_mm(self.screw_hole_diameter_m) / 2.0
        pocket_r = to_mm(self.nut_pocket_circumradius_m)
        pocket_depth = to_mm(self.nut_pocket_depth_m)
        y_screw = to_mm(self.screw_offset_m)
        x_screw = to_mm(self.fixture_screw_axial_m)

        body = b.Pos(0, 0, -height / 2.0) * b.Box(length, width, height)
        start, end = -length / 2.0 - 1.0, -length / 2.0 + depth
        body = body - b.Pos((start + end) / 2.0, 0, axis_z) * (
            b.Rot(0, 90, 0) * b.Cylinder(rod_r, end - start)
        )
        body = body - _groove(b, to_mm(self.groove_radius_m), length + 2.0)
        for side in (1.0, -1.0):
            body = body - _screw_cut(
                b, x_screw, side * y_screw, -height, 0.0, screw_r, pocket_r, pocket_depth
            )
        return body


class QfhFixtureClamp(QfhHubRodPart):
    """Clamp plate for a fixture: groove on the underside (z = 0), plate above it."""

    @property
    def part_name(self) -> str:
        return "qfh_fixture_clamp"

    def build(self) -> Any:
        b = require_cad()
        length = to_mm(self.fixture_length_m)
        width = to_mm(self.resolved_arm_width_m)
        t = to_mm(self.resolved_clamp_thickness_m)
        screw_r = to_mm(self.screw_hole_diameter_m) / 2.0
        y_screw = to_mm(self.screw_offset_m)
        x_screw = to_mm(self.fixture_screw_axial_m)
        plate = b.Pos(0, 0, t / 2.0) * b.Box(length, width, t)
        plate = plate - _groove(b, to_mm(self.groove_radius_m), length + 2.0)
        for side in (1.0, -1.0):
            plate = plate - b.Pos(x_screw, side * y_screw, t / 2.0) * b.Cylinder(screw_r, 2.0 * t)
        return plate


@dataclass(frozen=True)
class RodPlacement:
    """A rod in the assembled antenna: both ends on its axis, in millimetres."""

    name: str
    start_mm: tuple[float, float, float]
    end_mm: tuple[float, float, float]
    diameter_mm: float


class QfhHubRodPartSet(QfhHubRodPart):
    """All printed parts and rods of the hub-and-rod QFH supports."""

    @property
    def part_name(self) -> str:
        return "qfh_hubrod_parts"

    def build(self) -> Any:
        raise NotImplementedError("use instances() and build each part")

    def _common(self) -> dict[str, Any]:
        names = QfhHubRodPart.model_fields
        return {name: getattr(self, name) for name in names}

    def hub(self, kind: HubKind) -> QfhHub:
        return QfhHub(kind=kind, **self._common())

    def fixture(self) -> QfhFixture:
        return QfhFixture(**self._common())

    def clamp(self) -> QfhFixtureClamp:
        return QfhFixtureClamp(**self._common())

    def instances(self) -> list[PartInstance]:
        return [
            PartInstance("qfh_hub_upper", 1, self.hub("upper")),
            PartInstance("qfh_hub_lower_large", 1, self.hub("lower_large")),
            PartInstance("qfh_hub_lower_small", 1, self.hub("lower_small")),
            PartInstance("qfh_fixture", 8, self.fixture()),
            PartInstance("qfh_fixture_clamp", 8, self.clamp()),
        ]

    def _arms(self) -> list[tuple[HubKind, Loop, float]]:
        """(hub, loop, direction) of every arm: four at the top, two on each lower hub."""
        arms: list[tuple[HubKind, Loop, float]] = []
        for angle in (0.0, 180.0):
            arms.append(("upper", "large", angle))
        for angle in (90.0, 270.0):
            arms.append(("upper", "small", angle))
        for angle in (0.0, 180.0):
            arms.append(("lower_large", "large", angle))
        for angle in (90.0, 270.0):
            arms.append(("lower_small", "small", angle))
        return arms

    def _z(self, kind: HubKind) -> float:
        return -to_mm(self.hub(kind).distance_from_top_m)

    def placements(self) -> list[Placement]:
        out = []
        for kind in ("upper", "lower_large", "lower_small"):
            hub = self.hub(kind)
            out.append(Placement(hub.part_name, hub, (0.0, 0.0, self._z(kind)), 0.0))
        fixture, clamp = self.fixture(), self.clamp()
        for kind, loop, angle in self._arms():
            r = to_mm(self.fixture_center_radius_m(loop))
            x, y = r * math.cos(math.radians(angle)), r * math.sin(math.radians(angle))
            z = self._z(kind)
            out.append(Placement(fixture.part_name, fixture, (x, y, z), angle))
            out.append(Placement(clamp.part_name, clamp, (x, y, z), angle))
        return out

    def rod_placements(self) -> list[RodPlacement]:
        out = []
        for kind, loop, angle in self._arms():
            ux, uy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            r0 = to_mm(self.hub_socket_bottom_radius_m)
            r1 = to_mm(self.fixture_socket_bottom_radius_m(loop))
            z = self._z(kind) - to_mm(self.rod_axis_depth_m)
            out.append(
                RodPlacement(
                    f"qfh_rod_{loop}",
                    (r0 * ux, r0 * uy, z),
                    (r1 * ux, r1 * uy, z),
                    to_mm(self.rod_diameter_m),
                )
            )
        return out

    def rods(self) -> list[Rod]:
        return [
            Rod("qfh_rod_large", 4, self.rod_length_m("large"), self.rod_diameter_m),
            Rod("qfh_rod_small", 4, self.rod_length_m("small"), self.rod_diameter_m),
        ]

    @property
    def clamp_count(self) -> int:
        return 8

    @property
    def socket_count(self) -> int:
        return 8  # four on the upper hub, two on each lower hub

    @property
    def min_clamp_screw_length_m(self) -> float:
        return self.resolved_clamp_thickness_m + self.fixture_height_m

    def fasteners(self) -> list[FastenerUse]:
        per_clamp = self.fastener.screws_per_clamp
        return [
            FastenerUse(
                "clamp plates", self.clamp_count * per_clamp, self.min_clamp_screw_length_m
            ),
            FastenerUse("rod retention", self.socket_count, self.retention_screw_min_length_m),
        ]

    @property
    def screw_count(self) -> int:
        return sum(f.screws for f in self.fasteners())

    @property
    def nut_count(self) -> int:
        return self.screw_count

    def fit_problems(self) -> list[FitProblem]:
        problems = []
        for instance in self.instances():
            problem = self.print_settings.check_fit(instance.name, instance.part.size_mm())
            if problem is not None:
                problems.append(problem)
        return problems
