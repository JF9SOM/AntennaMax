"""Minimal NEC2 backend via PyNEC: input impedance at a single frequency."""

from __future__ import annotations

from antennamax.core.geometry import Geometry
from antennamax.core.units import hz_to_mhz


def input_impedance(
    geometry: Geometry, frequency_hz: float, feed_segment: int | None = None
) -> complex:
    """Input impedance (ohm) of free-space `geometry`, fed at the centre of wire 1.

    `feed_segment` is 1-based within the first wire; defaults to its middle segment
    (requires an odd segment count for a true centre feed).
    """
    from PyNEC import nec_context  # imported lazily; PyNEC is a required dependency

    if not geometry.wires:
        raise ValueError("geometry has no wires")
    wire0 = geometry.wires[0]
    if feed_segment is None:
        feed_segment = (wire0.segments + 1) // 2

    ctx = nec_context()
    geo = ctx.get_geometry()
    for tag, w in enumerate(geometry.wires, start=1):
        geo.wire(tag, w.segments, *w.start, *w.end, w.radius, 1.0, 1.0)
    ctx.geometry_complete(0)
    ctx.gn_card(-1, 0, 0, 0, 0, 0, 0, 0)  # free space
    ctx.ex_card(0, 1, feed_segment, 0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    ctx.fr_card(0, 1, hz_to_mhz(frequency_hz), 0.0)
    ctx.xq_card(0)
    z = ctx.get_input_parameters(0).get_impedance()[0]
    return complex(z)
