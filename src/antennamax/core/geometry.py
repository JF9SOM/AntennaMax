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


@dataclass(frozen=True)
class Feed:
    """A voltage source on one segment of a wire.

    `voltage` is the complex amplitude [V] with the e^{j omega t} convention: a source delayed
    by 90 degrees has phase -90 degrees, i.e. voltage = -1j.
    """

    wire: int  # 0-based index into Geometry.wires
    segment: int | None = None  # 1-based within the wire; None = the centre segment
    voltage: complex = 1.0

    def __post_init__(self) -> None:
        if self.wire < 0:
            raise ValueError("feed wire index must be >= 0")
        if self.segment is not None and self.segment < 1:
            raise ValueError("feed segment must be >= 1 (1-based)")
        if self.voltage == 0:
            raise ValueError("feed voltage must not be zero")


@dataclass
class Geometry:
    """Collection of wires and their sources.

    Sources: either `feeds` (any number of voltage sources with amplitude and phase) or, as a
    simple single-source shorthand, `feed_wire` (0-based index of the wire driven with 1 V at
    its centre segment). If `feeds` is non-empty it takes precedence and `feed_wire` is ignored.
    """

    wires: list[Wire] = field(default_factory=list)
    feed_wire: int = 0
    feeds: list[Feed] = field(default_factory=list)

    def resolved_feeds(self) -> list[Feed]:
        """The sources actually in use, with the shorthand expanded."""
        return list(self.feeds) if self.feeds else [Feed(self.feed_wire)]

    def feed_segment_number(self, feed: Feed) -> int:
        """1-based segment of `feed` (the centre segment if unspecified)."""
        wire = self.wires[feed.wire]
        return feed.segment if feed.segment is not None else (wire.segments + 1) // 2

    def validate_feeds(self) -> None:
        """Raise ValueError if a source points outside the wires or segments."""
        for i, feed in enumerate(self.resolved_feeds()):
            if not 0 <= feed.wire < len(self.wires):
                raise ValueError(f"feed {i}: wire index {feed.wire} is out of range")
            segments = self.wires[feed.wire].segments
            if not 1 <= self.feed_segment_number(feed) <= segments:
                raise ValueError(
                    f"feed {i}: segment {feed.segment} is out of range (wire has {segments})"
                )

    def add(self, wire: Wire) -> None:
        self.wires.append(wire)
