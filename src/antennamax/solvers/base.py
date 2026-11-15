"""Common solver interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from antennamax.core.geometry import Geometry


class SolverUnavailableError(RuntimeError):
    """Raised when a solver's optional dependency is not installed."""


@dataclass(frozen=True)
class Sweep:
    """List of frequencies in Hz."""

    frequencies_hz: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.frequencies_hz:
            raise ValueError("sweep needs at least one frequency")
        if any(f <= 0 for f in self.frequencies_hz):
            raise ValueError("frequencies must be positive")


@runtime_checkable
class Solver(Protocol):
    def supports(self, geometry: Geometry) -> bool: ...

    # TODO: return type becomes results.Result once the Result type exists.
    def run(self, geometry: Geometry, sweep: Sweep) -> object: ...
