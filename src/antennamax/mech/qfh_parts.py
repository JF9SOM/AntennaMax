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
from typing import Annotated, Any, Literal

from pydantic import Field, PositiveFloat, model_validator

from antennamax.mech.base import MM, FitProblem, Part, require_cad, to_mm
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

NOTCH_WIDTH_MM = 3.0  # tangential width of the orientation notches
# Orientation notch at +x on the bottom rim of the hubs and spreaders: radial depth, height.
ORIENTATION_NOTCH_DEPTH_MM = 1.5
ORIENTATION_NOTCH_HEIGHT_MM = 2.0

# How far the tip of a mast set screw reaches into the mast hole beyond the inner web.
MAST_SCREW_PROTRUSION_M = 1.0e-3


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
    # M3 set screws (grub screws, each with a captive nut) through the wall of the mast hole of
    # every spreader / hub: they hold it on the mast against turning and sliding. They sit at 45
    # degrees between the arms, 90 degrees apart.
    mast_screws_per_part: Annotated[int, Field(ge=1, le=4)] = 2
    # Drill guide collar (see QfhDrillGuide); defaults are derived from the walls and hole.
    drill_guide_wall_m: PositiveFloat | None = None  # default: 4 walls
    drill_guide_height_m: PositiveFloat | None = None  # default: 3 guide-hole diameters


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

    # --- mast set screws ------------------------------------------------------------------

    @property
    def mast_screw_directions_deg(self) -> tuple[float, ...]:
        """Between the arms (which lie at 0, 90, 180, 270 degrees), 90 degrees apart."""
        return tuple(45.0 + 90.0 * i for i in range(self.mast_screws_per_part))

    @property
    def mast_screw_nut_inner_radius_m(self) -> float:
        """The nut pocket starts a wall outside the mast hole (the web the screw passes)."""
        return self.mast_hole_diameter_m / 2.0 + self.wall_m

    @property
    def mast_screw_nut_outer_radius_m(self) -> float:
        return self.mast_screw_nut_inner_radius_m + self.nut_pocket_depth_m

    @property
    def mast_screw_min_rim_radius_m(self) -> float:
        """A wall outside the farthest corner of the nut pocket (its outer face, flat sides)."""
        far = math.hypot(self.mast_screw_nut_outer_radius_m, self.nut_pocket_across_flats_m / 2.0)
        return far + self.wall_m

    @property
    def mast_screw_min_length_m(self) -> float:
        """From the outer face of the nut: through the nut and the web, a little into the hole."""
        return self.nut_pocket_depth_m + self.wall_m + MAST_SCREW_PROTRUSION_M

    # --- drill guide collar ---------------------------------------------------------------

    @property
    def guide_hole_diameter_m(self) -> float:
        """The conductor passes through the mast: conductor diameter + clearance."""
        return self.print_settings.hole_diameter_m(self.qfh.diameter_m)

    @property
    def resolved_drill_guide_wall_m(self) -> float:
        """Default: thick enough for the nut pocket of the collar's set screw."""
        default = max(
            4.0 * self.wall_m, self.mast_screw_min_rim_radius_m - self.mast_hole_diameter_m / 2.0
        )
        return self.drill_guide_wall_m or default

    @property
    def resolved_drill_guide_height_m(self) -> float:
        return self.drill_guide_height_m or 3.0 * self.guide_hole_diameter_m

    @property
    def drill_guide_outer_diameter_m(self) -> float:
        return self.mast_hole_diameter_m + 2.0 * self.resolved_drill_guide_wall_m

    @property
    def guide_hole_below_top_m(self) -> float:
        """From the top face of the collar down to the centre of the guide hole."""
        return self.resolved_drill_guide_height_m / 2.0

    @property
    def drill_guide_notch_depth_m(self) -> float:
        """Orientation notch in the top face: leaves a wall above the guide hole."""
        return self.guide_hole_below_top_m - self.guide_hole_diameter_m / 2.0 - self.wall_m

    @property
    def drill_guide_screw_direction_deg(self) -> float:
        """The collar's set screw: 45 degrees from both guide hole axes (0/180 or 90/270 degrees)
        and well away from the notch at 0 degrees."""
        return 135.0

    @model_validator(mode="after")
    def _check_drill_guide(self) -> QfhSupportPart:
        if self.drill_guide_notch_depth_m < 0.5e-3:
            raise ValueError(
                "drill_guide_height_m is too small: the guide hole needs a wall above it and "
                "room for the orientation notch"
            )
        if self.guide_hole_below_top_m < self.nut_pocket_circumradius_m + self.wall_m - 1e-12:
            raise ValueError(
                "drill_guide_height_m is too small for the collar's set screw: a wall under the "
                "nut pocket is needed"
            )
        outer = self.drill_guide_outer_diameter_m / 2.0
        if outer < self.mast_screw_min_rim_radius_m - 1e-12:
            raise ValueError(
                "drill_guide_wall_m is too thin for the collar's set screw: the collar radius must "
                f"be at least {to_mm(self.mast_screw_min_rim_radius_m):.1f} mm"
            )
        return self

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
        """Mast hole plus a wall all round; at least thick enough for the set-screw nut pocket."""
        default = max(
            4.0 * self.wall_m, self.mast_screw_min_rim_radius_m - self.mast_hole_diameter_m / 2.0
        )
        wall = self.hub_wall_m or default
        return self.mast_hole_diameter_m + 2.0 * wall

    @property
    def mast_screw_axis_depth_m(self) -> float:
        """Axis of the set screws below the top face: a wall above the screw hole."""
        return self.screw_hole_diameter_m / 2.0 + self.wall_m

    @property
    def mast_boss_thickness_m(self) -> float:
        """The hub is a boss, thicker than the arms where the nut pockets of the set screws are."""
        pocket_bottom = self.mast_screw_axis_depth_m + self.nut_pocket_circumradius_m + self.wall_m
        return max(self.resolved_body_thickness_m, pocket_bottom)

    # --- along the arms --------------------------------------------------------------------

    def clamp_length_m(self, loop: Loop) -> float:
        """From the edge of the hub to Dc/2."""
        return self.loop_half_length_m(loop) - self.hub_diameter_m / 2.0

    def clamp_center_m(self, loop: Loop) -> float:
        """Distance of the clamp's middle (and of its screws) from the centre."""
        return self.hub_diameter_m / 2.0 + self.clamp_length_m(loop) / 2.0

    @model_validator(mode="after")
    def _check(self) -> QfhHolderPart:
        if self.hub_diameter_m / 2.0 < self.mast_screw_min_rim_radius_m - 1e-12:
            raise ValueError(
                "hub_wall_m is too thin for the mast set screws: the hub radius must be at least "
                f"{to_mm(self.mast_screw_min_rim_radius_m):.1f} mm"
            )
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


def mast_screw_cut(
    b: Any,
    part: QfhSupportPart,
    axis_z: float,
    rim_radius: float,
    angle: float,
    top_z: float = 0.0,
) -> Any:
    """Cut for one mast set screw, pointing radially at `angle` degrees (millimetres).

    A screw hole from the mast hole out through the rim, a hex pocket for the nut (axis radial,
    corners up and down, a wall out from the mast hole) and a slot above the pocket, open to the
    top face, through which the nut is dropped in.
    """
    mast_r = to_mm(part.mast_hole_diameter_m) / 2.0
    pocket_start = to_mm(part.mast_screw_nut_inner_radius_m)
    depth = to_mm(part.nut_pocket_depth_m)
    screw_r = to_mm(part.screw_hole_diameter_m) / 2.0
    pocket_r = to_mm(part.nut_pocket_circumradius_m)
    flats = to_mm(part.nut_pocket_across_flats_m)
    x0, x1 = mast_r - 1.0, rim_radius + 1.0
    hole = b.Pos((x0 + x1) / 2.0, 0, axis_z) * (b.Rot(0, 90, 0) * b.Cylinder(screw_r, x1 - x0))
    pocket = b.Pos(pocket_start, 0, axis_z) * (b.Rot(0, 90, 0) * _hex_prism(b, pocket_r, depth))
    top = top_z + 1.0  # the slot runs out of the top face
    slot = b.Pos(pocket_start + depth / 2.0, 0, (axis_z + top) / 2.0) * b.Box(
        depth, flats, top - axis_z
    )
    return b.Rot(0, 0, angle) * (hole + pocket + slot)


def orientation_notch_cut(b: Any, rim_radius: float, bottom_z: float) -> Any:
    """Notch in the bottom edge of the rim at +x (millimetres).

    +x is the direction of the upper spreader's +x arm, a large-loop arm: the lower and upper
    parts and the drill guide collars are all turned so that their +x marks point the same way.
    """
    depth, height = ORIENTATION_NOTCH_DEPTH_MM, ORIENTATION_NOTCH_HEIGHT_MM
    x0, x1 = rim_radius - depth, rim_radius + 1.0
    z0, z1 = bottom_z - 1.0, bottom_z + height
    return b.Pos((x0 + x1) / 2.0, 0, (z0 + z1) / 2.0) * b.Box(x1 - x0, NOTCH_WIDTH_MM, z1 - z0)


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

        # z from -t to 0; the top face (z = 0) is the conductor plane. The hub is a boss, thicker
        # than the arms, so that the set screws' nut pockets keep their walls.
        boss = to_mm(self.mast_boss_thickness_m)
        body = b.Pos(0, 0, -boss / 2) * b.Cylinder(hub_r, boss)
        for axis, loop in arms:
            length = 2.0 * to_mm(self.loop_half_length_m(loop))
            box = b.Box(length, width, t)
            body = body + b.Pos(0, 0, -t / 2) * (box if axis == "x" else b.Rot(0, 0, 90) * box)
        body = body - b.Pos(0, 0, -t / 2) * b.Cylinder(mast_r, 2 * boss)
        for angle in self.mast_screw_directions_deg:
            body = body - mast_screw_cut(
                b, self, -to_mm(self.mast_screw_axis_depth_m), hub_r, angle
            )
        # Orientation mark: a notch in the bottom edge of the hub at +x (the large-loop arm side).
        body = body - orientation_notch_cut(b, hub_r, -boss)
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


class QfhDrillGuide(QfhSupportPart):
    """Drill guide collar: a ring for the mast that shows where the lower conductor goes through.

    The lower horizontal conductor of each loop passes straight through the mast, H1 (large loop)
    and H2 (small loop) below the top of the antenna, in directions 90 degrees apart. The collar
    is slid onto the mast, its top face placed at (H - top face to hole centre) from the top; the
    guide hole through the wall is then drilled through, across the mast's diameter, with the
    mast's own drill bit. The hole is the conductor diameter plus clearance.

    Orientation: both collars have a notch in the top face at +x, the direction of the upper
    spreader's +x arm (a large-loop arm). The large collar's guide holes lie along x, in line
    with the notch (the large loop's conductor is parallel to the +-x arms); the small collar's
    lie along y, 90 degrees from the notch, in line with the +-y arms (small loop). Turn both
    collars so that the notches face the upper spreader's +x arm.

    The collar is modelled with the centre of the guide hole at z = 0; its top face is
    `guide_hole_below_top_m` above that.
    TODO(要確認): カラーのマストへの固定(はめあいの摩擦のみ。テープ等で仮止めする想定)は未設計。
    """

    loop: Loop

    @property
    def part_name(self) -> str:
        return f"qfh_drill_guide_{self.loop}"

    @property
    def distance_from_top_m(self) -> float:
        """The guide hole's distance from the top of the antenna: H1 or H2."""
        dims = self.qfh.dimensions
        return (dims.large if self.loop == "large" else dims.small).height_m

    @property
    def collar_top_from_top_m(self) -> float:
        """Where the top face of the collar goes: the hole's distance from the top, less the
        distance from the top face to the hole centre."""
        return self.distance_from_top_m - self.guide_hole_below_top_m

    def build(self) -> Any:
        b = require_cad()
        height = to_mm(self.resolved_drill_guide_height_m)
        inner_r = to_mm(self.mast_hole_diameter_m) / 2.0
        outer_r = to_mm(self.drill_guide_outer_diameter_m) / 2.0
        hole_r = to_mm(self.guide_hole_diameter_m) / 2.0
        notch_depth = to_mm(self.drill_guide_notch_depth_m)
        wall = to_mm(self.resolved_drill_guide_wall_m)

        collar = b.Cylinder(outer_r, height) - b.Cylinder(inner_r, 2 * height)
        # The guide hole: across the whole collar and the mast, along x (large) or y (small).
        axis = b.Rot(0, 90, 0) if self.loop == "large" else b.Rot(90, 0, 0)
        collar = collar - axis * b.Cylinder(hole_r, 2 * outer_r + 2.0)
        # Orientation notch at +x in the top face, across the wall.
        notch_z = height / 2.0 - notch_depth
        notch = b.Pos((inner_r + outer_r) / 2.0, 0, notch_z + (notch_depth + 1.0) / 2.0) * b.Box(
            wall + 1.0, NOTCH_WIDTH_MM, notch_depth + 1.0
        )
        collar = collar - notch
        # One M3 set screw holds the collar on the mast (same scheme as the hubs'), clear of the
        # guide hole and the notch.
        return collar - mast_screw_cut(
            b, self, 0.0, outer_r, self.drill_guide_screw_direction_deg, top_z=height / 2.0
        )


@dataclass(frozen=True)
class DrillGuideInfo:
    """Where to put a drill guide collar on the mast."""

    loop: str
    hole_from_top_m: float  # distance of the guide hole's centre from the top of the antenna
    top_face_to_hole_m: float  # the collar's reference dimension
    collar_top_from_top_m: float  # where the collar's top face goes
    hole_diameter_m: float


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


SITE_ORDER = ("upper", "lower_large", "lower_small")


@dataclass(frozen=True)
class PartRow:
    """Parts of one kind installed at one place: for the listing."""

    name: str
    site: str
    count: int
    distance_from_top_m: float
    size_mm: tuple[float, float, float]


def part_rows(part_set: Any) -> list[PartRow]:
    """The printed parts grouped by kind and installation site, from the placements.

    A kind that is installed at several heights (clamp plates and fixtures sit at the top and on
    both lower bars) gets one row per site, with that site's distance from the top.
    """
    instances = part_set.instances()
    sizes = {i.name: i.part.size_mm() for i in instances}
    order = {i.name: n for n, i in enumerate(instances)}
    groups: dict[tuple[str, str], list[Any]] = {}
    for p in part_set.placements():
        entry = groups.setdefault((p.name, p.site), [0, p.distance_from_top_m])
        entry[0] += 1
    keys = sorted(groups, key=lambda k: (order[k[0]], SITE_ORDER.index(k[1])))
    return [PartRow(n, s, groups[(n, s)][0], groups[(n, s)][1], sizes[n]) for n, s in keys]


def drill_guide_info(part_set: Any) -> list[DrillGuideInfo]:
    """The drill guide collars of a part set: where each guide hole is and where the collar goes."""
    out = []
    for instance in part_set.instances():
        part = instance.part
        if isinstance(part, QfhDrillGuide):
            out.append(
                DrillGuideInfo(
                    part.loop,
                    part.distance_from_top_m,
                    part.guide_hole_below_top_m,
                    part.collar_top_from_top_m,
                    part.guide_hole_diameter_m,
                )
            )
    return out


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
    site: str = ""  # where it is installed: "upper", "lower_large" or "lower_small"

    @property
    def distance_from_top_m(self) -> float:
        """How far below the top of the antenna the part's conductor plane lies; negative for a
        part placed above the top."""
        return -self.position_mm[2] / MM


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

    def drill_guide(self, loop: Loop) -> QfhDrillGuide:
        return QfhDrillGuide(loop=loop, **self._common())

    def instances(self) -> list[PartInstance]:
        """The distinct parts and how many of each are needed."""
        return [
            PartInstance("qfh_upper_spreader", 1, self.upper()),
            PartInstance("qfh_lower_spreader_large", 1, self.lower("large")),
            PartInstance("qfh_lower_spreader_small", 1, self.lower("small")),
            PartInstance("qfh_clamp_large", 4, self.clamp("large")),
            PartInstance("qfh_clamp_small", 4, self.clamp("small")),
            PartInstance("qfh_drill_guide_large", 1, self.drill_guide("large")),
            PartInstance("qfh_drill_guide_small", 1, self.drill_guide("small")),
        ]

    def placements(self) -> list[Placement]:
        """Where every physical part sits when the antenna is assembled."""
        out: list[Placement] = []
        upper, lower_l, lower_s = self.upper(), self.lower("large"), self.lower("small")
        out.append(Placement(upper.part_name, upper, (0.0, 0.0, 0.0), 0.0, "upper"))
        out.append(
            Placement(
                lower_l.part_name,
                lower_l,
                (0.0, 0.0, -to_mm(lower_l.distance_from_top_m)),
                0.0,
                "lower_large",
            )
        )
        out.append(
            Placement(
                lower_s.part_name,
                lower_s,
                (0.0, 0.0, -to_mm(lower_s.distance_from_top_m)),
                90.0,
                "lower_small",
            )
        )
        large, small = self.clamp("large"), self.clamp("small")
        cl, cs = to_mm(large.clamp_center_m("large")), to_mm(small.clamp_center_m("small"))
        z_lower_large = -to_mm(lower_l.distance_from_top_m)
        z_lower_small = -to_mm(lower_s.distance_from_top_m)
        for site, z in (("upper", 0.0), ("lower_large", z_lower_large)):
            for sign in (1.0, -1.0):  # the large loop's clamps: upper arms and lower bar
                out.append(Placement(large.part_name, large, (sign * cl, 0.0, z), 0.0, site))
        for site, z in (("upper", 0.0), ("lower_small", z_lower_small)):
            for sign in (1.0, -1.0):
                out.append(Placement(small.part_name, small, (0.0, sign * cs, z), 90.0, site))
        for loop, site in (("large", "lower_large"), ("small", "lower_small")):
            guide = self.drill_guide(loop)
            out.append(
                Placement(
                    guide.part_name, guide, (0.0, 0.0, -to_mm(guide.distance_from_top_m)), 0.0, site
                )
            )
        return out

    def rods(self) -> list[Rod]:
        """Purchased rods: none, the spreaders are single printed parts."""
        return []

    def fasteners(self) -> list[FastenerUse]:
        return [
            FastenerUse(
                "clamp plates",
                self.clamp_count * self.fastener.screws_per_clamp,
                self.min_screw_length_m,
            ),
            FastenerUse("mast set screws", self.mast_screw_count, self.mast_screw_min_length_m),
            FastenerUse("drill guide set screws", 2, self.mast_screw_min_length_m),
        ]

    @property
    def mast_screw_count(self) -> int:
        """Set screws in the mast holes: the upper spreader and the two lower bars."""
        return 3 * self.mast_screws_per_part

    def drill_guides(self) -> list[DrillGuideInfo]:
        return drill_guide_info(self)

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
        return sum(f.screws for f in self.fasteners())

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
