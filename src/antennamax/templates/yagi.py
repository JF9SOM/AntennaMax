"""Yagi-Uda template (free space).

Elements are parallel to the y axis and spaced along the x axis (the boom). By convention
list them from the reflector towards the directors, i.e. with increasing `position_m`; the
main beam then points to +x.
"""

from __future__ import annotations

from pydantic import NonNegativeInt, PositiveFloat, model_validator

from antennamax.core.geometry import Geometry, Wire
from antennamax.core.segmentation import (
    DEFAULT_SEGMENTS_PER_WAVELENGTH,
    Segmentation,
    choose_common_segments,
)
from antennamax.templates.base import SIModel, Template

# TODO(要確認): ブーム補正(金属ブームによるエレメント実効長の短縮)は未実装。
# エレメントはブームを貫通しない独立した細線として扱う(docs/VERIFICATION.md 参照)。
# TODO(要確認): 既定の 20 分割/波長と「全エレメント同一分割数」が十分な精度か未検証。
# 分割数は core.segmentation で決める(セグメント長 < λ/10 かつ Δ/a > 2)。


class YagiElement(SIModel):
    position_m: float  # along the boom (x)
    length_m: PositiveFloat
    diameter_m: PositiveFloat

    @model_validator(mode="after")
    def _thin_wire(self) -> YagiElement:
        if self.diameter_m >= self.length_m:
            raise ValueError("diameter_m must be smaller than length_m")
        return self


class Yagi(Template):
    center_frequency_hz: PositiveFloat
    elements: list[YagiElement]
    feed_index: NonNegativeInt  # 0-based index into `elements`
    segments_per_wavelength: PositiveFloat = DEFAULT_SEGMENTS_PER_WAVELENGTH  # target density
    max_frequency_hz: PositiveFloat | None = None  # top of the sweep; default: centre frequency

    @model_validator(mode="after")
    def _check(self) -> Yagi:
        if len(self.elements) < 2:
            raise ValueError("a Yagi needs at least 2 elements")
        if self.feed_index >= len(self.elements):
            raise ValueError("feed_index is out of range")
        positions = [e.position_m for e in self.elements]
        if len(set(positions)) != len(positions):
            raise ValueError("element positions must be distinct")
        if self.max_frequency_hz is not None and self.max_frequency_hz < self.center_frequency_hz:
            raise ValueError("max_frequency_hz must not be below the centre frequency")
        return self

    @property
    def segmentation(self) -> Segmentation:
        """One odd segment count for all elements, decided by the most demanding element.

        Raises SegmentationError if no count satisfies segment length < lambda/10 and
        delta/a > 2 at the highest frequency.
        """
        return choose_common_segments(
            [(e.length_m, e.diameter_m / 2) for e in self.elements],
            self.max_frequency_hz or self.center_frequency_hz,
            self.segments_per_wavelength,
            odd=True,
        )

    @property
    def segments(self) -> int:
        return self.segmentation.segments

    def to_geometry(self) -> Geometry:
        n = self.segments
        wires = [
            Wire(
                (e.position_m, -e.length_m / 2, 0.0),
                (e.position_m, e.length_m / 2, 0.0),
                e.diameter_m / 2,
                n,
            )
            for e in self.elements
        ]
        return Geometry(wires, feed_wire=self.feed_index)
