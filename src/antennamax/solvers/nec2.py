"""NEC2 backend via PyNEC (free space)."""

from __future__ import annotations

import math

import numpy as np

from antennamax.core.geometry import Geometry
from antennamax.core.units import deg_to_rad, hz_to_mhz
from antennamax.results.result import Result
from antennamax.solvers.base import Sweep


def _simulate(
    geometry: Geometry,
    frequency_hz: float,
    feed_segment: int | None,
    pattern_resolution_deg: float | None,
) -> tuple[complex, np.ndarray | None]:
    """Run NEC2 at one frequency. Returns (impedance, gain_dbi[n_theta, n_phi] or None)."""
    from PyNEC import nec_context  # imported lazily; PyNEC is a required dependency

    if not geometry.wires:
        raise ValueError("geometry has no wires")
    if not 0 <= geometry.feed_wire < len(geometry.wires):
        raise ValueError("feed_wire is out of range")
    if feed_segment is None:
        feed_segment = (geometry.wires[geometry.feed_wire].segments + 1) // 2

    ctx = nec_context()
    geo = ctx.get_geometry()
    for tag, w in enumerate(geometry.wires, start=1):
        geo.wire(tag, w.segments, *w.start, *w.end, w.radius, 1.0, 1.0)
    ctx.geometry_complete(0)
    ctx.gn_card(-1, 0, 0, 0, 0, 0, 0, 0)  # free space
    ctx.ex_card(0, geometry.feed_wire + 1, feed_segment, 0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    ctx.fr_card(0, 1, hz_to_mhz(frequency_hz), 0.0)
    if pattern_resolution_deg is None:
        ctx.xq_card(0)
    else:
        n_theta, n_phi = _pattern_shape(pattern_resolution_deg)
        d = pattern_resolution_deg
        # RP: normal mode, total gain in dB, no normalisation; theta 0..180, phi 0..360-d
        ctx.rp_card(0, n_theta, n_phi, 0, 0, 0, 0, 0.0, 0.0, d, d, 0.0, 0.0)
    z = complex(ctx.get_input_parameters(0).get_impedance()[0])
    gain = None
    if pattern_resolution_deg is not None:
        gain = _nec_gain_to_dbi(ctx.get_radiation_pattern(0).get_gain())
    return z, gain


# NEC2 prints exact nulls as this floor value instead of -infinity.
_NEC_GAIN_FLOOR_DB = -999.0


def _nec_gain_to_dbi(gain: np.ndarray) -> np.ndarray:
    """Convert NEC2's -999.99 dB null marker to -inf, keeping the Result solver-agnostic."""
    gain = np.asarray(gain, dtype=float).copy()
    gain[gain <= _NEC_GAIN_FLOOR_DB] = -np.inf
    return gain


def _pattern_shape(resolution_deg: float) -> tuple[int, int]:
    n_theta = round(180.0 / resolution_deg) + 1
    n_phi = round(360.0 / resolution_deg)
    return n_theta, n_phi


def input_impedance(
    geometry: Geometry, frequency_hz: float, feed_segment: int | None = None
) -> complex:
    """Input impedance (ohm) of free-space `geometry`, fed at the centre of `geometry.feed_wire`.

    `feed_segment` is 1-based within the fed wire; defaults to its middle segment
    (requires an odd segment count for a true centre feed).
    """
    return _simulate(geometry, frequency_hz, feed_segment, None)[0]


class Nec2Solver:
    """NEC2 solver (free space only for now).

    If `pattern_resolution_deg` is given, the full-sphere radiation pattern is computed on a
    grid with that step: theta 0..180 deg (inclusive), phi 0..360-step deg. Gain is total
    gain in dBi; exact nulls are -inf (NEC2's -999.99 dB marker is converted).
    """

    def __init__(
        self,
        pattern_resolution_deg: float | None = None,
        z0: float = 50.0,
        feed_segment: int | None = None,
    ) -> None:
        if pattern_resolution_deg is not None:
            if pattern_resolution_deg <= 0 or pattern_resolution_deg > 180:
                raise ValueError("pattern_resolution_deg must be in (0, 180]")
            for span in (180.0, 360.0):
                ratio = span / pattern_resolution_deg
                if not math.isclose(ratio, round(ratio)):
                    raise ValueError("pattern_resolution_deg must divide 180 evenly")
        self.pattern_resolution_deg = pattern_resolution_deg
        self.z0 = z0
        self.feed_segment = feed_segment

    def supports(self, geometry: Geometry) -> bool:
        return len(geometry.wires) > 0

    def run(self, geometry: Geometry, sweep: Sweep) -> Result:
        if not self.supports(geometry):
            raise ValueError("geometry is not supported by Nec2Solver")
        zs: list[complex] = []
        gains: list[np.ndarray] = []
        for f in sweep.frequencies_hz:
            z, gain = _simulate(geometry, f, self.feed_segment, self.pattern_resolution_deg)
            zs.append(z)
            if gain is not None:
                gains.append(gain)
        result = Result(
            frequencies_hz=np.array(sweep.frequencies_hz),
            impedance=np.array(zs),
            z0=self.z0,
        )
        if self.pattern_resolution_deg is not None:
            n_theta, n_phi = _pattern_shape(self.pattern_resolution_deg)
            d = self.pattern_resolution_deg
            result.theta_rad = deg_to_rad(d) * np.arange(n_theta)
            result.phi_rad = deg_to_rad(d) * np.arange(n_phi)
            result.gain_dbi = np.array(gains)
        return result
