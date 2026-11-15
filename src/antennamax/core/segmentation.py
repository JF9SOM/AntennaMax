"""Segment-count selection for wires.

Constraints (evaluated at the highest frequency of the sweep):
  a. segment length < lambda / 10;
  b. segment length / radius (delta / a) > 2, the lower limit of NEC2's extended thin-wire
     kernel.
The count follows a target density (segments per wavelength); if (b) forbids it the count is
reduced, if (a) demands more it is raised, and if the two cannot be reconciled a
SegmentationError is raised.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

C = 299_792_458.0  # speed of light, m/s

DEFAULT_SEGMENTS_PER_WAVELENGTH = 20.0

# lambda/10 is the usual moment-method rule of thumb (TODO(要確認): 出典未照合)。
MAX_SEGMENT_WAVELENGTH_FRACTION = 0.1
# Thresholds on delta / a (segment length / conductor radius), from the NEC2 guidelines (Burke &
# Poggio, NEC-2 Manual): the standard thin-wire kernel needs delta / a > 8, the extended
# thin-wire kernel (EK card) allows delta / a > 2. Single source of truth: solvers/thin_wire.py
# imports these.
# TODO(要確認): 閾値は NEC2 ガイドラインの一般的な説明に基づく。マニュアル原典での記述・適用条件は
# 未照合(docs/VERIFICATION.md 参照)。
STANDARD_KERNEL_MIN_SEGMENT_TO_RADIUS = 8.0
EXTENDED_KERNEL_MIN_SEGMENT_TO_RADIUS = 2.0
# The lower limit that segmentation enforces: that of the extended kernel.
MIN_SEGMENT_TO_RADIUS = EXTENDED_KERNEL_MIN_SEGMENT_TO_RADIUS


class SegmentationError(ValueError):
    """No segment count satisfies both constraints for this frequency and conductor."""


class Reason(StrEnum):
    TARGET_DENSITY = "target_density"  # the requested segments per wavelength was usable
    MAX_SEGMENT_LENGTH = "max_segment_length"  # raised to keep the segment shorter than lambda/10
    SEGMENT_TO_RADIUS = "segment_to_radius"  # reduced to keep delta/a above 2


@dataclass(frozen=True)
class Segmentation:
    segments: int
    reason: Reason
    n_target: int  # count asked for by the density (after the odd adjustment)
    n_min: int  # smallest count allowed by constraint a (after the odd adjustment)
    n_max: int  # largest count allowed by constraint b (after the odd adjustment)
    # Index of the wire that sets the binding bound (always 0 for a single wire); for the
    # target density, the longest wire.
    limiting_wire: int


def _bounds(length: float, radius: float, wavelength: float) -> tuple[int, int]:
    """(n_min, n_max) for one wire, as integers: n_min <= N <= n_max (may be empty)."""
    n_min = math.floor(length / (MAX_SEGMENT_WAVELENGTH_FRACTION * wavelength)) + 1  # strict <
    n_max = math.ceil(length / (MIN_SEGMENT_TO_RADIUS * radius)) - 1  # strict >
    return n_min, n_max


def _check(length: float, radius: float) -> None:
    if length <= 0 or radius <= 0:
        raise ValueError("length and radius must be positive")


def choose_common_segments(
    wires: Sequence[tuple[float, float]],
    max_frequency_hz: float,
    segments_per_wavelength: float = DEFAULT_SEGMENTS_PER_WAVELENGTH,
    odd: bool = False,
) -> Segmentation:
    """One segment count for several wires, set by the most demanding one.

    `wires` holds (length_m, radius_m) pairs. The target density and constraint (a) are driven
    by the longest wire, constraint (b) by the wire with the smallest length / radius.
    """
    if not wires:
        raise ValueError("no wires")
    if max_frequency_hz <= 0 or segments_per_wavelength <= 0:
        raise ValueError("max_frequency_hz and segments_per_wavelength must be positive")
    for length, radius in wires:
        _check(length, radius)
    wavelength = C / max_frequency_hz

    longest = max(range(len(wires)), key=lambda i: wires[i][0])
    n_min = _bounds(wires[longest][0], wires[longest][1], wavelength)[0]
    limits = [_bounds(length, radius, wavelength)[1] for length, radius in wires]
    thickest = min(range(len(wires)), key=lambda i: limits[i])
    n_max = limits[thickest]
    n_target = max(1, math.ceil(segments_per_wavelength * wires[longest][0] / wavelength))

    if odd:  # centre feed: round the target and the lower bound up, the upper bound down
        n_target += (n_target + 1) % 2
        n_min += (n_min + 1) % 2
        n_max -= (n_max + 1) % 2
    if n_max < 1 or n_min > n_max:
        details = ", ".join(
            f"wire {i}: length {length:.4g} m, radius {radius:.4g} m"
            for i, (length, radius) in enumerate(wires)
        )
        raise SegmentationError(
            f"cannot segment this geometry for NEC2 at {max_frequency_hz / 1e6:.6g} MHz"
            f"{' (odd counts only)' if odd else ''}: segment length < lambda/10 needs at least "
            f"{n_min} segments (wire {longest}), but delta/a > {MIN_SEGMENT_TO_RADIUS:g} allows at "
            f"most {max(n_max, 0)} (wire {thickest}). Use a thinner conductor or a lower "
            f"frequency. [{details}]"
        )

    if n_target < n_min:
        return Segmentation(n_min, Reason.MAX_SEGMENT_LENGTH, n_target, n_min, n_max, longest)
    if n_target > n_max:
        return Segmentation(n_max, Reason.SEGMENT_TO_RADIUS, n_target, n_min, n_max, thickest)
    return Segmentation(n_target, Reason.TARGET_DENSITY, n_target, n_min, n_max, longest)


def choose_segments(
    length_m: float,
    radius_m: float,
    max_frequency_hz: float,
    segments_per_wavelength: float = DEFAULT_SEGMENTS_PER_WAVELENGTH,
    odd: bool = False,
) -> Segmentation:
    """Segment count for one wire (see the module docstring). `odd=True` for a centre feed."""
    return choose_common_segments(
        [(length_m, radius_m)], max_frequency_hz, segments_per_wavelength, odd
    )
