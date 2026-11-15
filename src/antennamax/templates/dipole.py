"""Centre-fed dipole template (free space; element along the y axis)."""

from __future__ import annotations

from pydantic import PositiveFloat, field_validator, model_validator

from antennamax.core.geometry import Geometry, Wire
from antennamax.core.segmentation import (
    DEFAULT_SEGMENTS_PER_WAVELENGTH,
    Segmentation,
    choose_segments,
)
from antennamax.templates.base import Template

C = 299_792_458.0  # speed of light, m/s

# TODO(要確認): 共振長の目安 0.95 x (lambda/2) は一般的な経験則。導体径依存を含め
# NEC2 での実際の共振長(X=0)と比較して確認する(docs/VERIFICATION.md 参照)。
RESONANCE_SHORTENING = 0.95


class Dipole(Template):
    center_frequency_hz: PositiveFloat
    length_m: PositiveFloat | None = None  # total length; default: resonance estimate
    diameter_m: PositiveFloat
    # Odd, so that the feed sits at the centre. If omitted it is chosen by core.segmentation
    # (see `segmentation`); if given it is used as is and the solver only warns about delta/a.
    segments: int | None = None
    segments_per_wavelength: PositiveFloat = DEFAULT_SEGMENTS_PER_WAVELENGTH  # target density
    max_frequency_hz: PositiveFloat | None = None  # top of the sweep; default: centre frequency

    @field_validator("segments")
    @classmethod
    def _odd_segments(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v < 1 or v % 2 == 0:
            raise ValueError("segments must be a positive odd integer")
        return v

    @model_validator(mode="after")
    def _thin_wire(self) -> Dipole:
        if self.diameter_m >= self.resolved_length_m:
            raise ValueError("diameter_m must be smaller than the length")
        return self

    @model_validator(mode="after")
    def _max_frequency(self) -> Dipole:
        if self.max_frequency_hz is not None and self.max_frequency_hz < self.center_frequency_hz:
            raise ValueError("max_frequency_hz must not be below the centre frequency")
        return self

    @property
    def resolved_length_m(self) -> float:
        if self.length_m is not None:
            return self.length_m
        return RESONANCE_SHORTENING * C / self.center_frequency_hz / 2

    @property
    def segmentation(self) -> Segmentation | None:
        """The automatic choice and its reason; None if `segments` was given explicitly."""
        if self.segments is not None:
            return None
        return choose_segments(
            self.resolved_length_m,
            self.diameter_m / 2,
            self.max_frequency_hz or self.center_frequency_hz,
            self.segments_per_wavelength,
            odd=True,
        )

    @property
    def resolved_segments(self) -> int:
        auto = self.segmentation
        return self.segments if auto is None else auto.segments

    def to_geometry(self) -> Geometry:
        half = self.resolved_length_m / 2
        wire = Wire(
            (0.0, -half, 0.0), (0.0, half, 0.0), self.diameter_m / 2, self.resolved_segments
        )
        return Geometry([wire])
