"""Base of the 3D-printable parts (build123d).

Parts are described by pydantic parameters in SI units (the `*_mm` input spelling works as
everywhere); the CAD model itself is built in millimetres, the unit of STL and STEP files, so the
conversion happens here, at the boundary. Dimensions that follow from the antenna come from the
template (for example `Qfh.dimensions`); they are never typed into the part code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import NonNegativeFloat

from antennamax.core.optional import require
from antennamax.templates.base import SIModel

MM = 1000.0  # millimetres per metre


def to_mm(value_m: float) -> float:
    """Metres to millimetres (the CAD unit)."""
    return value_m * MM


def require_cad() -> Any:
    """Import build123d or explain how to install it."""
    return require("build123d", "build 3D-printable parts", extra="cad")


class PrintSettings(SIModel):
    """Printer settings shared by all parts."""

    # Clearance added to the nominal diameter of holes (and to any other fit). 0.2 mm is a common
    # starting point for FDM printers.
    # TODO(要確認): 0.2 mm が実機・材料で適切かは未確認(嵌合テストピースは未実装)。
    clearance_m: NonNegativeFloat = 0.2e-3

    def hole_diameter_m(self, nominal_m: float) -> float:
        """Hole diameter for a part of the given nominal diameter: nominal + clearance."""
        return nominal_m + self.clearance_m


class Part(SIModel, ABC):
    """A printable part: parameters -> build123d shape -> STL / STEP."""

    print_settings: PrintSettings = PrintSettings()

    @abstractmethod
    def build(self) -> Any:
        """The build123d shape, in millimetres."""

    def export(self, out_dir: Path, stem: str) -> list[Path]:
        """Write `<stem>.stl` and `<stem>.step` into `out_dir` (created if needed)."""
        b3d = require_cad()
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        shape = self.build()
        stl, step = out_dir / f"{stem}.stl", out_dir / f"{stem}.step"
        b3d.export_stl(shape, str(stl))
        b3d.export_step(shape, str(step))
        return [stl, step]
