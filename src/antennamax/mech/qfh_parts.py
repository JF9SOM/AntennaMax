"""Supports for a QFH: spreaders with a groove and clamp plates that hold the conductors.

The loop conductors are laid in half-round grooves cut into the top face of a spreader and
clamped from above by a plate with the matching half-round groove underneath; together the two
grooves form a round channel of conductor diameter + clearance. A clamp plate is held by two M3
screws that run through the plate and the spreader into hex nuts captured in pockets in the
spreader's underside.

Parts (the model has both loops' top ends at the feed; the large loop's bottom conductor is
H1 and the small loop's H2 below it):

  qfh_upper_spreader      x1  cross with four arms and a mast hole (the coax runs inside the
                              mast): large-loop arms along +-x, small-loop arms along +-y;
                              at the top of the antenna (distance from top 0)
  qfh_lower_spreader_large x1 straight bar along x with a central boss and mast hole, the groove
                              continuous across the whole bar (and the mast hole); H1 from the top
  qfh_lower_spreader_small x1 the same along y; H2 from the top
  qfh_clamp_large          x4 clamp plate for one large-loop arm
  qfh_clamp_small          x4 clamp plate for one small-loop arm

All dimensions come from the QFH template: a groove and its clamp run from the centre out to
Dc/2 (Dc = D - 2R, the straight part of the horizontal conductor after the bend correction);
beyond that the conductor bends and the arm leaves room for it. Every part is modelled with its
conductor plane at z = 0 (the spreader below it, the clamp above it).

TODO(要確認): 強度(腕の幅・板厚・ねじの保持力)は未検証。
TODO(要確認): 下部スプレッダーのマスト穴は、導体が穴の上を横切る前提(マストは下部スプレッダーの
下側で止める想定)。マストの固定方法は未検討。
TODO(要確認): 巻き数が 0.5 の整数倍でないとき、上部の導体位置は下部と回転してずれる(未対応)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import PositiveFloat, model_validator

from antennamax.mech.base import FitProblem, Part, require_cad, to_mm
from antennamax.mech.fasteners import Fastener, standard_screw_length_mm
from antennamax.templates.base import SIModel
from antennamax.templates.qfh import Qfh

# Default mast: a PVC water pipe. Japanese VP (rigid PVC) pipes, JIS K 6741, have outer diameters
# of about 18 (VP13), 22 (VP16), 26 (VP20), 32 (VP25), 38 (VP30) mm; VP20 (26 mm) is taken as a
# common choice for a light antenna mast.
# TODO(要確認): VP 管の外径(JIS K 6741 の値)は記憶に基づくもので、原典未確認。購入する管を測って
# `mast_outer_diameter_mm` で指定すること。
DEFAULT_MAST_OUTER_DIAMETER_M = 0.026

Loop = Literal["large", "small"]


class QfhHolderParams(SIModel):
    """Parameters common to all QFH support parts (defaults are derived, see the properties)."""

    qfh: Qfh
    mast_outer_diameter_m: PositiveFloat = DEFAULT_MAST_OUTER_DIAMETER_M
    arm_width_m: PositiveFloat | None = None  # default: just wide enough for the screws and nuts
    body_thickness_m: PositiveFloat | None = (
        None  # spreader thickness; default: nut pocket + 2 walls
    )
    clamp_thickness_m: PositiveFloat | None = None  # default: groove radius + 2 walls
    hub_wall_m: PositiveFloat | None = None  # wall around the mast hole; default: 4 walls
    fastener: Fastener = Fastener()


class QfhSupportPart(QfhHolderParams, Part):
    """Derived dimensions shared by all support parts (metres unless a name ends in _mm)."""

    # --- fasteners and grooves ---------------------------------------------------------

    @property
    def wall_m(self) -> float:
        return self.print_settings.min_wall_m

    @property
    def groove_radius_m(self) -> float:
        """Half of conductor diameter + clearance: two grooves make this round channel."""
        return self.print_settings.hole_diameter_m(self.qfh.diameter_m) / 2.0

    @property
    def screw_hole_diameter_m(self) -> float:
        return self.print_settings.hole_diameter_m(self.fastener.screw_diameter_m)

    @property
    def nut_pocket_across_flats_m(self) -> float:
        return self.print_settings.hole_diameter_m(self.fastener.nut_across_flats_m)

    @property
    def nut_pocket_circumradius_m(self) -> float:
        return self.nut_pocket_across_flats_m / math.sqrt(3.0)

    @property
    def nut_pocket_depth_m(self) -> float:
        return self.print_settings.hole_diameter_m(self.fastener.nut_thickness_m)

    @property
    def screw_offset_m(self) -> float:
        """Distance of the screws from the groove axis, clear of the groove and the nut pocket."""
        return self.groove_radius_m + self.wall_m + self.nut_pocket_across_flats_m / 2.0

    # --- plate dimensions ----------------------------------------------------------------

    @property
    def min_arm_width_m(self) -> float:
        return 2.0 * (self.screw_offset_m + self.nut_pocket_across_flats_m / 2.0 + self.wall_m)

    @property
    def resolved_arm_width_m(self) -> float:
        return self.arm_width_m or self.min_arm_width_m

    @property
    def resolved_body_thickness_m(self) -> float:
        return self.body_thickness_m or self.nut_pocket_depth_m + 2.0 * self.wall_m

    @property
    def resolved_clamp_thickness_m(self) -> float:
        return self.clamp_thickness_m or self.groove_radius_m + 2.0 * self.wall_m

    @property
    def mast_hole_diameter_m(self) -> float:
        return self.print_settings.hole_diameter_m(self.mast_outer_diameter_m)

    @model_validator(mode="after")
    def _check_arm_width(self) -> QfhSupportPart:
        if self.resolved_arm_width_m < self.min_arm_width_m - 1e-12:
            raise ValueError(
                f"arm_width_m must be at least {to_mm(self.min_arm_width_m):.1f} mm for the screws"
            )
        return self

    def loop_half_length_m(self, loop: Loop) -> float:
        """Dc/2: how far from the centre the groove and the clamp reach."""
        dims = self.qfh.dimensions
        return (dims.large if loop == "large" else dims.small).compensated_horizontal_m / 2.0


class QfhHolderPart(QfhSupportPart):
    """Integrated spreaders: the hub, the arms and the groove are one printed part."""

    @property
    def hub_diameter_m(self) -> float:
        wall = self.hub_wall_m or 4.0 * self.wall_m
        return self.mast_hole_diameter_m + 2.0 * wall

    # --- along the arms --------------------------------------------------------------------

    def clamp_length_m(self, loop: Loop) -> float:
        """From the edge of the hub to Dc/2."""
        return self.loop_half_length_m(loop) - self.hub_diameter_m / 2.0

    def clamp_center_m(self, loop: Loop) -> float:
        """Distance of the clamp's middle (and of its screws) from the centre."""
        return self.hub_diameter_m / 2.0 + self.clamp_length_m(loop) / 2.0

    @model_validator(mode="after")
    def _check(self) -> QfhHolderPart:
        needed = 2.0 * self.nut_pocket_circumradius_m + 2.0 * self.wall_m
        for loop in ("large", "small"):
            available = self.clamp_length_m(loop)
            if available < needed:
                raise ValueError(
                    f"the {loop} loop's arm is too short for a clamp: {to_mm(available):.1f} mm "
                    f"between the hub and Dc/2, {to_mm(needed):.1f} mm needed (smaller mast or hub)"
                )
        return self


# --- CAD helpers (millimetres) -------------------------------------------------------------


def _groove(b: Any, radius: float, length: float) -> Any:
    """Cylinder along x, centred on the origin: the conductor channel (axis at z = 0)."""
    return b.Rot(0, 90, 0) * b.Cylinder(radius, length)


def _hex_prism(b: Any, circumradius: float, height: float) -> Any:
    """Hexagonal prism standing on z = 0, corners on the x axis."""
    points = [
        b.Vector(
            circumradius * math.cos(math.radians(60 * i)),
            circumradius * math.sin(math.radians(60 * i)),
            0,
        )
        for i in range(6)
    ]
    return b.extrude(b.Face(b.Wire.make_polygon(points, close=True)), amount=height)


# --- parts ---------------------------------------------------------------------------------


class _Spreader(QfhHolderPart):
    """A spreader body: arms along the x and/or y axis, a boss with the mast hole, grooves."""

    def _arms(self) -> list[tuple[str, Loop]]:
        raise NotImplementedError

    def build(self) -> Any:
        b = require_cad()
        arms = self._arms()
        t = to_mm(self.resolved_body_thickness_m)
        width = to_mm(self.resolved_arm_width_m)
        hub_r = to_mm(self.hub_diameter_m) / 2.0
        mast_r = to_mm(self.mast_hole_diameter_m) / 2.0
        groove_r = to_mm(self.groove_radius_m)
        screw_r = to_mm(self.screw_hole_diameter_m) / 2.0
        pocket_r = to_mm(self.nut_pocket_circumradius_m)
        pocket_depth = to_mm(self.nut_pocket_depth_m)
        y_screw = to_mm(self.screw_offset_m)

        # z from -t to 0; the top face (z = 0) is the conductor plane.
        body = b.Pos(0, 0, -t / 2) * b.Cylinder(hub_r, t)
        for axis, loop in arms:
            length = 2.0 * to_mm(self.loop_half_length_m(loop))
            box = b.Box(length, width, t)
            body = body + b.Pos(0, 0, -t / 2) * (box if axis == "x" else b.Rot(0, 0, 90) * box)
        body = body - b.Pos(0, 0, -t / 2) * b.Cylinder(mast_r, 2 * t)
        for axis, loop in arms:
            length = 2.0 * to_mm(self.loop_half_length_m(loop)) + 2.0
            groove = _groove(b, groove_r, length)
            body = body - (groove if axis == "x" else b.Rot(0, 0, 90) * groove)
            # Two screws per clamp, on either side of the groove, in each of the two arms.
            for sign in (1.0, -1.0):
                for side in (1.0, -1.0):
                    x = sign * to_mm(self.clamp_center_m(loop))
                    hole = b.Pos(0, 0, -t / 2) * b.Cylinder(screw_r, 2 * t)
                    pocket = b.Pos(0, 0, -t) * _hex_prism(b, pocket_r, pocket_depth)
                    cut = b.Pos(x, side * y_screw, 0) * (hole + pocket)
                    body = body - (cut if axis == "x" else b.Rot(0, 0, 90) * cut)
        return body


class QfhUpperSpreader(_Spreader):
    """Four arms at the top of the antenna, around the mast (the coax runs inside the mast)."""

    @property
    def part_name(self) -> str:
        return "qfh_upper_spreader"

    def _arms(self) -> list[tuple[str, Loop]]:
        return [("x", "large"), ("y", "small")]


class QfhLowerSpreader(_Spreader):
    """A straight bar for one loop's bottom conductor, groove continuous end to end."""

    loop: Loop

    @property
    def part_name(self) -> str:
        return f"qfh_lower_spreader_{self.loop}"

    @property
    def distance_from_top_m(self) -> float:
        dims = self.qfh.dimensions
        return (dims.large if self.loop == "large" else dims.small).height_m

    def _arms(self) -> list[tuple[str, Loop]]:
        return [("x" if self.loop == "large" else "y", self.loop)]


class QfhClamp(QfhHolderPart):
    """Clamp plate for one arm, along x, groove on the underside (z = 0), plate above it."""

    loop: Loop

    @property
    def part_name(self) -> str:
        return f"qfh_clamp_{self.loop}"

    def build(self) -> Any:
        b = require_cad()
        length = to_mm(self.clamp_length_m(self.loop))
        width = to_mm(self.resolved_arm_width_m)
        t = to_mm(self.resolved_clamp_thickness_m)
        screw_r = to_mm(self.screw_hole_diameter_m) / 2.0
        y_screw = to_mm(self.screw_offset_m)
        plate = b.Pos(0, 0, t / 2) * b.Box(length, width, t)
        plate = plate - _groove(b, to_mm(self.groove_radius_m), length + 2.0)
        for side in (1.0, -1.0):
            plate = plate - b.Pos(0, side * y_screw, t / 2) * b.Cylinder(screw_r, 2 * t)
        return plate


# --- the set ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rod:
    """A purchased rod (not printed), cut to length."""

    name: str
    count: int
    length_m: float
    diameter_m: float

    @property
    def total_length_m(self) -> float:
        return self.count * self.length_m


@dataclass(frozen=True)
class FastenerUse:
    """Screws (each with a hex nut) of one kind."""

    purpose: str
    screws: int
    min_length_m: float

    @property
    def nuts(self) -> int:
        return self.screws

    @property
    def screw_length_mm(self) -> int:
        return standard_screw_length_mm(to_mm(self.min_length_m))


@dataclass(frozen=True)
class PartInstance:
    name: str
    count: int
    part: Part

    @property
    def distance_from_top_m(self) -> float:
        return self.part.distance_from_top_m


@dataclass(frozen=True)
class Placement:
    """One physical part in the assembled antenna (z = 0 is the top conductor plane)."""

    name: str
    part: Part
    position_mm: tuple[float, float, float]
    rotation_deg: float  # about z


class QfhPartSet(QfhHolderPart):
    """All printable support parts of a QFH."""

    @property
    def part_name(self) -> str:
        return "qfh_parts"

    def build(self) -> Any:  # a set has no single shape
        raise NotImplementedError("use instances() and build each part")

    def _common(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in QfhHolderParams.model_fields} | {
            "print_settings": self.print_settings
        }

    def upper(self) -> QfhUpperSpreader:
        return QfhUpperSpreader(**self._common())

    def lower(self, loop: Loop) -> QfhLowerSpreader:
        return QfhLowerSpreader(loop=loop, **self._common())

    def clamp(self, loop: Loop) -> QfhClamp:
        return QfhClamp(loop=loop, **self._common())

    def instances(self) -> list[PartInstance]:
        """The distinct parts and how many of each are needed."""
        return [
            PartInstance("qfh_upper_spreader", 1, self.upper()),
            PartInstance("qfh_lower_spreader_large", 1, self.lower("large")),
            PartInstance("qfh_lower_spreader_small", 1, self.lower("small")),
            PartInstance("qfh_clamp_large", 4, self.clamp("large")),
            PartInstance("qfh_clamp_small", 4, self.clamp("small")),
        ]

    def placements(self) -> list[Placement]:
        """Where every physical part sits when the antenna is assembled."""
        out: list[Placement] = []
        upper, lower_l, lower_s = self.upper(), self.lower("large"), self.lower("small")
        out.append(Placement(upper.part_name, upper, (0.0, 0.0, 0.0), 0.0))
        out.append(
            Placement(
                lower_l.part_name, lower_l, (0.0, 0.0, -to_mm(lower_l.distance_from_top_m)), 0.0
            )
        )
        out.append(
            Placement(
                lower_s.part_name, lower_s, (0.0, 0.0, -to_mm(lower_s.distance_from_top_m)), 90.0
            )
        )
        large, small = self.clamp("large"), self.clamp("small")
        cl, cs = to_mm(large.clamp_center_m("large")), to_mm(small.clamp_center_m("small"))
        z_lower_large = -to_mm(lower_l.distance_from_top_m)
        z_lower_small = -to_mm(lower_s.distance_from_top_m)
        for z in (0.0, z_lower_large):  # the large loop's clamps: upper arms and lower bar
            for sign in (1.0, -1.0):
                out.append(Placement(large.part_name, large, (sign * cl, 0.0, z), 0.0))
        for z in (0.0, z_lower_small):
            for sign in (1.0, -1.0):
                out.append(Placement(small.part_name, small, (0.0, sign * cs, z), 90.0))
        return out

    def rods(self) -> list[Rod]:
        """Purchased rods: none, the spreaders are single printed parts."""
        return []

    def fasteners(self) -> list[FastenerUse]:
        return [FastenerUse("clamp plates", self.screw_count, self.min_screw_length_m)]

    def fit_problems(self) -> list[FitProblem]:
        """Printed parts that exceed the build volume."""
        problems = []
        for instance in self.instances():
            problem = self.print_settings.check_fit(instance.name, instance.part.size_mm())
            if problem is not None:
                problems.append(problem)
        return problems

    @property
    def clamp_count(self) -> int:
        return sum(i.count for i in self.instances() if "clamp" in i.name)

    @property
    def screw_count(self) -> int:
        return self.clamp_count * self.fastener.screws_per_clamp

    @property
    def nut_count(self) -> int:
        return self.screw_count

    @property
    def min_screw_length_m(self) -> float:
        """Through a clamp plate and a spreader, to the outer face of the nut."""
        return self.upper().resolved_clamp_thickness_m + self.upper().resolved_body_thickness_m

    @property
    def screw_length_mm(self) -> int:
        return standard_screw_length_mm(to_mm(self.min_screw_length_m))
