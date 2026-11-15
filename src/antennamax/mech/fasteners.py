"""Fasteners used by the printed parts (an M3 screw and hex nut)."""

from __future__ import annotations

from pydantic import PositiveFloat, PositiveInt

from antennamax.templates.base import SIModel

# Standard metric screw lengths [mm] used to round a required minimum length up.
STANDARD_SCREW_LENGTHS_MM = (6, 8, 10, 12, 14, 16, 20, 25, 30, 35, 40)


class Fastener(SIModel):
    """A screw with a captive hex nut. Defaults: M3.

    Nominal values: M3 thread diameter 3.0 mm; ISO 4032 hex nut M3 with 5.5 mm across flats and
    2.4 mm thickness. TODO(要確認): 値は一般的な M3 の規格値の記憶に基づく。購入するナットを実測して
    `nut_across_flats_mm` / `nut_thickness_mm` を指定すること。
    """

    name: str = "M3"
    screw_diameter_m: PositiveFloat = 3.0e-3
    nut_across_flats_m: PositiveFloat = 5.5e-3
    nut_thickness_m: PositiveFloat = 2.4e-3
    screws_per_clamp: PositiveInt = 2


def standard_screw_length_mm(minimum_mm: float) -> int:
    """Smallest standard screw length that is at least `minimum_mm` long."""
    for length in STANDARD_SCREW_LENGTHS_MM:
        if length >= minimum_mm:
            return length
    return int(minimum_mm) + 1
