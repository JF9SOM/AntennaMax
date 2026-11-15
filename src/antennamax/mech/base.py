"""Base of the 3D-printable parts (build123d).

Parts are described by pydantic parameters in SI units (the `*_mm` input spelling works as
everywhere); the CAD model itself is built in millimetres, the unit of STL and STEP files, so the
conversion happens here, at the boundary. Dimensions that follow from the antenna come from the
template (for example `Qfh.dimensions`); they are never typed into the part code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import NonNegativeFloat, PositiveFloat

from antennamax.core.optional import require
from antennamax.templates.base import SIModel

MM = 1000.0  # millimetres per metre


def to_mm(value_m: float) -> float:
    """Metres to millimetres (the CAD unit)."""
    return value_m * MM


def require_cad() -> Any:
    """Import build123d or explain how to install it."""
    return require("build123d", "build 3D-printable parts", extra="cad")


@dataclass(frozen=True)
class FitProblem:
    """A part that does not fit the printer's build volume."""

    name: str
    size_mm: tuple[float, float, float]
    build_volume_mm: tuple[float, float, float]
    # How far each dimension exceeds the limit [mm], in the order (longer plan side, shorter
    # plan side, height); 0 where it fits.
    excess_mm: tuple[float, float, float]

    def message(self) -> str:
        labels = ("length", "width", "height")
        parts = [
            f"{label} +{excess:.1f} mm"
            for label, excess in zip(labels, self.excess_mm, strict=True)
            if excess > 0
        ]
        x, y, z = self.size_mm
        bx, by, bz = self.build_volume_mm
        return (
            f"part '{self.name}' ({x:.1f} x {y:.1f} x {z:.1f} mm) exceeds the build volume "
            f"{bx:g} x {by:g} x {bz:g} mm: {', '.join(parts)}"
        )


class PrintSettings(SIModel):
    """Printer settings shared by all parts."""

    # Clearance added to the nominal diameter of holes (and to any other fit). 0.2 mm is a common
    # starting point for FDM printers.
    # TODO(要確認): 0.2 mm が実機・材料で適切かは未確認(嵌合テストピースは未実装)。
    clearance_m: NonNegativeFloat = 0.2e-3
    # Thinnest wall that prints reliably: about three perimeters of a 0.4 mm nozzle.
    # TODO(要確認): 一般的な目安(0.4 mm ノズルの外周 3 本)で、強度・材料での確認は未実施。
    min_wall_m: PositiveFloat = 1.2e-3
    # Build volume (x, y, height) in metres. The default 220 x 220 x 250 mm is typical of
    # entry-level FDM printers.
    # TODO(要確認): 実際のプリンターの造形範囲に合わせて設定すること。
    build_volume_m: tuple[PositiveFloat, PositiveFloat, PositiveFloat] = (0.22, 0.22, 0.25)

    def hole_diameter_m(self, nominal_m: float) -> float:
        """Hole diameter for a part of the given nominal diameter: nominal + clearance."""
        return nominal_m + self.clearance_m

    def check_fit(self, name: str, size_mm: tuple[float, float, float]) -> FitProblem | None:
        """Does a part of this size (printed flat, in either plan orientation) fit?"""
        plan = sorted(size_mm[:2], reverse=True)
        bed = sorted((to_mm(self.build_volume_m[0]), to_mm(self.build_volume_m[1])), reverse=True)
        excess = (
            max(0.0, plan[0] - bed[0]),
            max(0.0, plan[1] - bed[1]),
            max(0.0, size_mm[2] - to_mm(self.build_volume_m[2])),
        )
        if not any(e > 1e-9 for e in excess):
            return None
        volume = tuple(to_mm(v) for v in self.build_volume_m)
        return FitProblem(name, size_mm, volume, excess)  # type: ignore[arg-type]


class Part(SIModel, ABC):
    """A printable part: parameters -> build123d shape -> STL / STEP."""

    print_settings: PrintSettings = PrintSettings()

    @property
    @abstractmethod
    def part_name(self) -> str:
        """File stem and listing name."""

    @property
    def distance_from_top_m(self) -> float:
        """Where the part sits in the antenna: its conductor plane, measured down from the top."""
        return 0.0

    @abstractmethod
    def build(self) -> Any:
        """The build123d shape, in millimetres."""

    def size_mm(self) -> tuple[float, float, float]:
        """Outer dimensions (x, y, z) of the shape in millimetres."""
        size = self.build().bounding_box().size
        return (size.X, size.Y, size.Z)

    def export(self, out_dir: Path, stem: str | None = None) -> list[Path]:
        """Write `<stem>.stl` and `<stem>.step` into `out_dir` (created if needed)."""
        b3d = require_cad()
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        shape = self.build()
        stem = stem or self.part_name
        stl, step = out_dir / f"{stem}.stl", out_dir / f"{stem}.step"
        b3d.export_stl(shape, str(stl))
        b3d.export_step(shape, str(step))
        return [stl, step]
