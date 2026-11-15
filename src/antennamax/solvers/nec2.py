"""NEC2 backend via PyNEC (free space)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from antennamax.core.geometry import Geometry
from antennamax.core.units import deg_to_rad, hz_to_mhz
from antennamax.results.result import Result
from antennamax.solvers import thin_wire
from antennamax.solvers.base import Sweep

ExtendedKernel = bool | Literal["auto"]


@dataclass
class _Simulation:
    impedances: list[complex]  # one per source, in the order of Geometry.resolved_feeds()
    gain: np.ndarray | None = None  # [n_theta, n_phi] dBi
    e_theta: np.ndarray | None = None  # [n_theta, n_phi] complex, NEC2 scale
    e_phi: np.ndarray | None = None


def _simulate(
    geometry: Geometry,
    frequency_hz: float,
    feed_segment: int | None,
    pattern_resolution_deg: float | None,
    extended_kernel: bool = False,
) -> _Simulation:
    """Run NEC2 at one frequency."""
    from PyNEC import nec_context  # imported lazily; PyNEC is a required dependency

    if not geometry.wires:
        raise ValueError("geometry has no wires")
    if feed_segment is not None and geometry.feeds:
        raise ValueError("feed_segment cannot be combined with Geometry.feeds")
    geometry.validate_feeds()
    feeds = geometry.resolved_feeds()

    ctx = nec_context()
    geo = ctx.get_geometry()
    for tag, w in enumerate(geometry.wires, start=1):
        geo.wire(tag, w.segments, *w.start, *w.end, w.radius, 1.0, 1.0)
    ctx.geometry_complete(0)
    if extended_kernel:
        ctx.set_extended_thin_wire_kernel(True)  # NEC2 EK card
    ctx.gn_card(-1, 0, 0, 0, 0, 0, 0, 0)  # free space
    for feed in feeds:
        segment = feed_segment if feed_segment is not None else geometry.feed_segment_number(feed)
        v = complex(feed.voltage)  # e^{j omega t}: EX takes the real and imaginary parts
        ctx.ex_card(0, feed.wire + 1, segment, 0, v.real, v.imag, 0.0, 0.0, 0.0, 0.0)
    ctx.fr_card(0, 1, hz_to_mhz(frequency_hz), 0.0)
    if pattern_resolution_deg is None:
        ctx.xq_card(0)
    else:
        n_theta, n_phi = _pattern_shape(pattern_resolution_deg)
        d = pattern_resolution_deg
        # RP: normal mode, total gain in dB, no normalisation; theta 0..180, phi 0..360-d
        ctx.rp_card(0, n_theta, n_phi, 0, 0, 0, 0, 0.0, 0.0, d, d, 0.0, 0.0)
    # NEC2 reports one input impedance per source, in the order of the EX cards.
    impedances = [complex(z) for z in ctx.get_input_parameters(0).get_impedance()]
    if len(impedances) != len(feeds):
        raise RuntimeError(f"NEC2 returned {len(impedances)} impedances for {len(feeds)} sources")
    sim = _Simulation(impedances)
    if pattern_resolution_deg is not None:
        rp = ctx.get_radiation_pattern(0)
        sim.gain = _nec_gain_to_dbi(rp.get_gain())
        sim.e_theta = _grid(rp.get_e_theta(), n_theta, n_phi)
        sim.e_phi = _grid(rp.get_e_phi(), n_theta, n_phi)
    return sim


def _grid(flat, n_theta: int, n_phi: int) -> np.ndarray:
    """NEC2's flat field arrays run theta fastest (phi-major): index = i_phi * n_theta + i_theta.

    Verified against get_gain(): 10 log10(|E_theta|^2 + |E_phi|^2) differs from the gain grid by
    a constant only for this ordering (tests/test_polarization.py).
    """
    return np.asarray(flat, dtype=complex).reshape(n_phi, n_theta).T


# NEC2 prints exact nulls as this floor value instead of -infinity.
_NEC_GAIN_FLOOR_DB = -999.0


def _nec_gain_to_dbi(gain: np.ndarray) -> np.ndarray:
    """Convert NEC2's -999.99 dB null marker to -inf, keeping the Result solver-agnostic."""
    gain = np.asarray(gain, dtype=float).copy()
    gain[gain <= _NEC_GAIN_FLOOR_DB] = -np.inf
    return gain


def _validate_extended_kernel(value: object) -> ExtendedKernel:
    if value is True or value is False or value == "auto":
        return value  # type: ignore[return-value]
    raise ValueError('extended_kernel must be True, False or "auto"')


def _prepare(geometry: Geometry, setting: ExtendedKernel, stacklevel: int) -> bool:
    """Resolve the extended-kernel setting ("auto": on if any delta/a < 8) and warn."""
    if not geometry.wires:
        raise ValueError("geometry has no wires")
    use = thin_wire.needs_extended_kernel(geometry) if setting == "auto" else bool(setting)
    thin_wire.warn_if_out_of_range(geometry, use, stacklevel=stacklevel + 1)
    return use


def _pattern_shape(resolution_deg: float) -> tuple[int, int]:
    n_theta = round(180.0 / resolution_deg) + 1
    n_phi = round(360.0 / resolution_deg)
    return n_theta, n_phi


def input_impedance(
    geometry: Geometry,
    frequency_hz: float,
    feed_segment: int | None = None,
    extended_kernel: ExtendedKernel = "auto",
) -> complex:
    """Input impedance (ohm) of free-space `geometry`, fed at the centre of `geometry.feed_wire`.

    `feed_segment` is 1-based within the fed wire; defaults to its middle segment
    (requires an odd segment count for a true centre feed). Warns with ThinWireWarning if a wire
    is outside the thin-wire guideline; `extended_kernel` is as in Nec2Solver.
    """
    use = _prepare(geometry, _validate_extended_kernel(extended_kernel), stacklevel=2)
    return _simulate(geometry, frequency_hz, feed_segment, None, use).impedances[0]


class Nec2Solver:
    """NEC2 solver (free space only for now).

    If `pattern_resolution_deg` is given, the full-sphere radiation pattern is computed on a
    grid with that step: theta 0..180 deg (inclusive), phi 0..360-step deg. Gain is total
    gain in dBi; exact nulls are -inf (NEC2's -999.99 dB marker is converted).

    Thin-wire check: every wire's segment length / radius (delta/a) is computed; wires with
    delta/a < 8 raise a ThinWireWarning, or with the extended kernel on only wires below 2 raise
    a ThinWireOutOfRangeWarning. `extended_kernel`
    selects NEC2's extended thin-wire kernel: True, False, or "auto" (the default), which turns
    it on if any wire has delta/a < 8. The setting used is recorded in `Result.meta`.
    """

    def __init__(
        self,
        pattern_resolution_deg: float | None = None,
        z0: float = 50.0,
        feed_segment: int | None = None,
        extended_kernel: ExtendedKernel = "auto",
    ) -> None:
        self.extended_kernel = _validate_extended_kernel(extended_kernel)
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
        use_extended = _prepare(geometry, self.extended_kernel, stacklevel=2)
        sims = [
            _simulate(geometry, f, self.feed_segment, self.pattern_resolution_deg, use_extended)
            for f in sweep.frequencies_hz
        ]
        pattern: dict = {}
        if self.pattern_resolution_deg is not None:
            n_theta, n_phi = _pattern_shape(self.pattern_resolution_deg)
            d = deg_to_rad(self.pattern_resolution_deg)
            pattern = {
                "theta_rad": d * np.arange(n_theta),
                "phi_rad": d * np.arange(n_phi),
                "gain_dbi": np.array([s.gain for s in sims]),
                "e_theta": np.array([s.e_theta for s in sims]),
                "e_phi": np.array([s.e_phi for s in sims]),
            }
        return Result(
            frequencies_hz=np.array(sweep.frequencies_hz),
            impedance=np.array([s.impedances[0] for s in sims]),
            feed_impedances=np.array([s.impedances for s in sims]),
            z0=self.z0,
            meta={
                "solver": "nec2",
                "extended_kernel": use_extended,
                "min_segment_to_radius": min(thin_wire.ratios(geometry)),
                "n_feeds": len(geometry.resolved_feeds()),
            },
            **pattern,
        )
