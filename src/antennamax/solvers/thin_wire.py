"""Thin-wire applicability checks for the NEC2 moment-method solver.

Thresholds on the segment length / conductor radius ratio (delta / a), from the NEC2
guidelines (Burke & Poggio, NEC-2 Manual; Part III User's Guide): the standard thin-wire
kernel needs delta / a > 8, the extended thin-wire kernel (EK card) allows delta / a > 2.
"""

from __future__ import annotations

import math
import warnings

from antennamax.core.geometry import Geometry, Wire

# TODO(要確認): 閾値は NEC2 ガイドライン(標準カーネル Δ/a > 8、拡張カーネル Δ/a > 2)の
# 一般的な説明に基づく。マニュアル原典での記述・適用条件は未照合(docs/VERIFICATION.md 参照)。
STANDARD_KERNEL_MIN_RATIO = 8.0
EXTENDED_KERNEL_MIN_RATIO = 2.0

OK = "ok"
STANDARD_OUT_OF_RANGE = "standard_out_of_range"  # delta/a < 8: outside the standard kernel
EXTENDED_OUT_OF_RANGE = "extended_out_of_range"  # delta/a < 2: outside even the extended kernel


class ThinWireWarning(UserWarning):
    """A wire violates the standard-kernel thin-wire guideline (delta / a < 8)."""


class ThinWireOutOfRangeWarning(ThinWireWarning):
    """A wire is outside even the extended-kernel guideline (delta / a < 2): stronger warning."""


def segment_to_radius_ratio(wire: Wire) -> float:
    """delta / a: segment length divided by conductor radius."""
    return math.dist(wire.start, wire.end) / wire.segments / wire.radius


def wire_status(ratio: float, extended_kernel: bool = False) -> str:
    """Classify delta/a for the kernel in use.

    Standard kernel: OK from 8; below 8 STANDARD_OUT_OF_RANGE; below 2 EXTENDED_OUT_OF_RANGE.
    Extended kernel: OK from 2 (the standard-kernel limit no longer applies); below 2
    EXTENDED_OUT_OF_RANGE.
    """
    if ratio < EXTENDED_KERNEL_MIN_RATIO:
        return EXTENDED_OUT_OF_RANGE
    if not extended_kernel and ratio < STANDARD_KERNEL_MIN_RATIO:
        return STANDARD_OUT_OF_RANGE
    return OK


def ratios(geometry: Geometry) -> list[float]:
    return [segment_to_radius_ratio(w) for w in geometry.wires]


def needs_extended_kernel(geometry: Geometry) -> bool:
    """True if any wire is outside the standard-kernel guideline."""
    return any(r < STANDARD_KERNEL_MIN_RATIO for r in ratios(geometry))


def warn_if_out_of_range(geometry: Geometry, extended_kernel: bool, stacklevel: int = 2) -> None:
    """Emit one warning listing the wires outside the guideline of the kernel in use.

    Standard kernel: wires with delta/a < 8 (ThinWireWarning; the stronger
    ThinWireOutOfRangeWarning if any is below 2). Extended kernel: only wires with delta/a < 2
    (ThinWireOutOfRangeWarning); 2 <= delta/a < 8 is within its guideline and stays silent.
    """
    limit = EXTENDED_KERNEL_MIN_RATIO if extended_kernel else STANDARD_KERNEL_MIN_RATIO
    bad = [(i, r) for i, r in enumerate(ratios(geometry)) if r < limit]
    if not bad:
        return
    severe = any(r < EXTENDED_KERNEL_MIN_RATIO for _, r in bad)
    listing = ", ".join(f"wire {i} (delta/a = {r:.2f})" for i, r in bad)
    kernel = "ON" if extended_kernel else "OFF"
    if severe:
        category = ThinWireOutOfRangeWarning
        head = (
            f"thin-wire approximation: delta/a < {EXTENDED_KERNEL_MIN_RATIO:g}, outside even the "
            "extended-kernel guideline"
        )
    else:
        category = ThinWireWarning
        head = (
            f"thin-wire approximation: delta/a < {STANDARD_KERNEL_MIN_RATIO:g}, outside the "
            "standard-kernel guideline"
        )
    message = (
        f"{head}: {listing}. Extended thin-wire kernel is {kernel} "
        f"(guideline delta/a > {EXTENDED_KERNEL_MIN_RATIO:g}). "
        "Results may be inaccurate; use fewer segments or a thinner conductor."
    )
    warnings.warn(message, category, stacklevel=stacklevel)
