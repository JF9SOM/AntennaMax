"""QFH spreader: a cross-shaped plate that holds the loop conductors and sits on the mast.

Dimensions come from the QFH template (`Qfh.dimensions`): the large loop's conductor holes sit
at +-D1/2 on the x axis, the small loop's at +-D2/2 on the y axis (D = the loop's horizontal
separator, centre to centre of the conductors). A hole is the conductor diameter plus the print
clearance; the central hole is the mast's outer diameter plus the clearance.

The same plate serves at the top and the bottom of the antenna. That holds when the helix turns
through a multiple of half a turn (the default 0.5 turn maps the conductor positions onto
themselves, +-D/2). For other turns the conductors at the top are rotated against those at the
bottom and the top plate would need a rotated hole pattern.
TODO(要確認): 巻き数が 0.5 の整数倍でないときの上部用スプレッダー(穴パターンの回転)は未対応。
"""

from __future__ import annotations

from typing import Any

from pydantic import PositiveFloat, model_validator

from antennamax.mech.base import Part, require_cad, to_mm
from antennamax.templates.qfh import Qfh

# Default mast: a PVC water pipe. Japanese VP (rigid PVC) pipes, JIS K 6741, have outer diameters
# of about 18 (VP13), 22 (VP16), 26 (VP20), 32 (VP25), 38 (VP30) mm; VP20 (26 mm) is taken as a
# common choice for a light antenna mast.
# TODO(要確認): VP 管の外径(JIS K 6741 の値)は記憶に基づくもので、原典未確認。購入する管を測って
# `mast_outer_diameter_mm` で指定すること。
DEFAULT_MAST_OUTER_DIAMETER_M = 0.026

# Arm width, plate thickness and the wall around holes are multiples of the conductor hole
# diameter unless given. TODO(要確認): 強度の根拠は未確認(PLA/PETG/ASA での曲げ強度・たわみ)。
ARM_WIDTH_FACTOR = 3.0  # arm width = 3 x hole diameter (a wall of one hole diameter each side)
THICKNESS_FACTOR = 2.0  # plate thickness = 2 x hole diameter
END_MARGIN_FACTOR = 1.0  # wall beyond the outer edge of a conductor hole = 1 x hole diameter
HUB_WALL_FACTOR = 1.0  # hub wall around the mast hole, in multiples of the arm width


class QfhSpreader(Part):
    qfh: Qfh
    mast_outer_diameter_m: PositiveFloat = DEFAULT_MAST_OUTER_DIAMETER_M
    arm_width_m: PositiveFloat | None = None  # default: 3 x conductor hole diameter
    thickness_m: PositiveFloat | None = None  # default: 2 x conductor hole diameter
    end_margin_m: PositiveFloat | None = None  # default: 1 x conductor hole diameter

    # --- derived dimensions (metres) ------------------------------------------------------

    @property
    def conductor_hole_diameter_m(self) -> float:
        return self.print_settings.hole_diameter_m(self.qfh.diameter_m)

    @property
    def mast_hole_diameter_m(self) -> float:
        return self.print_settings.hole_diameter_m(self.mast_outer_diameter_m)

    @property
    def resolved_arm_width_m(self) -> float:
        return self.arm_width_m or ARM_WIDTH_FACTOR * self.conductor_hole_diameter_m

    @property
    def resolved_thickness_m(self) -> float:
        return self.thickness_m or THICKNESS_FACTOR * self.conductor_hole_diameter_m

    @property
    def resolved_end_margin_m(self) -> float:
        return self.end_margin_m or END_MARGIN_FACTOR * self.conductor_hole_diameter_m

    @property
    def hub_diameter_m(self) -> float:
        return self.mast_hole_diameter_m + 2.0 * HUB_WALL_FACTOR * self.resolved_arm_width_m

    @property
    def hole_centers_m(self) -> list[tuple[float, float]]:
        """Conductor hole centres (x, y) in metres: +-D1/2 on x (large), +-D2/2 on y (small)."""
        dims = self.qfh.dimensions
        a, b = dims.large.horizontal_m / 2.0, dims.small.horizontal_m / 2.0
        return [(a, 0.0), (-a, 0.0), (0.0, b), (0.0, -b)]

    def arm_half_length_m(self, horizontal_m: float) -> float:
        """Centre to the end of an arm: D/2 + hole radius + end margin."""
        return (
            horizontal_m / 2.0 + self.conductor_hole_diameter_m / 2.0 + self.resolved_end_margin_m
        )

    @model_validator(mode="after")
    def _check(self) -> QfhSpreader:
        hub_radius = self.hub_diameter_m / 2.0
        hole_radius = self.conductor_hole_diameter_m / 2.0
        for loop in (self.qfh.dimensions.large, self.qfh.dimensions.small):
            if loop.horizontal_m / 2.0 - hole_radius <= hub_radius:
                raise ValueError(
                    "the mast hub is too large for this loop: a conductor hole would overlap it "
                    "(smaller mast_outer_diameter, or a larger antenna)"
                )
        if self.resolved_arm_width_m < self.conductor_hole_diameter_m:
            raise ValueError("arm_width_m must be at least the conductor hole diameter")
        return self

    # --- shape (millimetres) ----------------------------------------------------------------

    def build(self) -> Any:
        b3d = require_cad()
        dims = self.qfh.dimensions
        width = to_mm(self.resolved_arm_width_m)
        thickness = to_mm(self.resolved_thickness_m)
        hole_d = to_mm(self.conductor_hole_diameter_m)
        mast_d = to_mm(self.mast_hole_diameter_m)
        hub_d = to_mm(self.hub_diameter_m)
        z = b3d.Align.CENTER

        with b3d.BuildPart() as part:
            b3d.Cylinder(hub_d / 2.0, thickness, align=(z, z, z))
            # Large-loop arm along x, small-loop arm along y.
            large = 2.0 * to_mm(self.arm_half_length_m(dims.large.horizontal_m))
            small = 2.0 * to_mm(self.arm_half_length_m(dims.small.horizontal_m))
            b3d.Box(large, width, thickness, align=(z, z, z))
            b3d.Box(width, small, thickness, align=(z, z, z))
            # Holes through the whole plate: the mast, then the four conductors.
            b3d.Cylinder(mast_d / 2.0, thickness * 2.0, align=(z, z, z), mode=b3d.Mode.SUBTRACT)
            for x, y in self.hole_centers_m:
                with b3d.Locations((to_mm(x), to_mm(y), 0.0)):
                    b3d.Cylinder(
                        hole_d / 2.0, thickness * 2.0, align=(z, z, z), mode=b3d.Mode.SUBTRACT
                    )
        return part.part
