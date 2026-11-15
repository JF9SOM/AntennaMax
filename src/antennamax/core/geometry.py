"""Basic geometry primitives (SI units, right-handed, z up, ground at z=0)."""

from __future__ import annotations

from dataclasses import dataclass, field

Point = tuple[float, float, float]


@dataclass(frozen=True)
class Wire:
    """Straight wire. Coordinates and radius in metres."""

    start: Point
    end: Point
    radius: float
    segments: int

    def __post_init__(self) -> None:
        if self.radius <= 0:
            raise ValueError("radius must be positive")
        if self.segments < 1:
            raise ValueError("segments must be >= 1")
        if self.start == self.end:
            raise ValueError("wire start and end must differ")


@dataclass
class Geometry:
    """Collection of wires."""

    wires: list[Wire] = field(default_factory=list)

    def add(self, wire: Wire) -> None:
        self.wires.append(wire)
