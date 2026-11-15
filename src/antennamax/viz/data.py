"""Drawing data for `view` and `plot`. NumPy only: no GUI dependency, easy to test."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from antennamax.core.geometry import Geometry
from antennamax.io.design import LoadedDesign
from antennamax.results.result import Result
from antennamax.solvers import thin_wire
from antennamax.solvers.base import Sweep
from antennamax.solvers.nec2 import Nec2Solver

DEFAULT_PATTERN_RESOLUTION_DEG = 5.0
PATTERN_DYNAMIC_RANGE_DB = 30.0  # gain range shown below the peak
TARGET_WIRE_RADIUS_FRACTION = 0.012  # thickest wire is drawn about this fraction of the size


@dataclass(frozen=True)
class DesignRun:
    """Simulation results needed by the viewers."""

    design: LoadedDesign
    geometry: Geometry
    center_frequency_hz: float
    sweep_result: Result  # impedance over the design's sweep (no pattern)
    pattern_result: Result  # one frequency (the centre) with the full pattern


def center_frequency_hz(design: LoadedDesign) -> float:
    """The template's centre frequency, or the middle of the sweep if it has none."""
    f = getattr(design.template, "center_frequency_hz", None)
    if f is not None:
        return float(f)
    freqs = design.sweep.frequencies_hz
    return 0.5 * (freqs[0] + freqs[-1])


def simulate(design: LoadedDesign) -> DesignRun:
    """Run the impedance sweep and a single-frequency full-pattern calculation."""
    geometry = design.template.to_geometry()
    f0 = center_frequency_hz(design)
    resolution = design.pattern_resolution_deg or DEFAULT_PATTERN_RESOLUTION_DEG
    sweep_result = Nec2Solver().run(geometry, design.sweep)
    pattern_result = Nec2Solver(pattern_resolution_deg=resolution).run(geometry, Sweep((f0,)))
    return DesignRun(design, geometry, f0, sweep_result, pattern_result)


# --- 3D view -----------------------------------------------------------------------------


@dataclass(frozen=True)
class WireDraw:
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    radius: float  # true conductor radius [m]
    display_radius: float  # radius used for drawing [m]
    is_fed: bool
    ratio: float  # segment length / radius
    status: str  # thin_wire.OK / STANDARD_OUT_OF_RANGE / EXTENDED_OUT_OF_RANGE


def _bounds(geometry: Geometry) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    pts = np.array([p for w in geometry.wires for p in (w.start, w.end)], dtype=float)
    return pts.min(axis=0), pts.max(axis=0)


def geometry_size(geometry: Geometry) -> float:
    """Largest extent of the wire bounding box [m]."""
    lo, hi = _bounds(geometry)
    return float(np.max(hi - lo))


def geometry_center(geometry: Geometry) -> NDArray[np.float64]:
    lo, hi = _bounds(geometry)
    return 0.5 * (lo + hi)


def wire_draws(geometry: Geometry, extended_kernel: bool = False) -> tuple[list[WireDraw], float]:
    """Wires with drawing radii, and the magnification applied to the true radii.

    Radii keep their proportions; they are magnified (never reduced) so that the thickest wire
    is visible at about 1.2 % of the structure size. Wire status follows the solver's rules for
    the kernel in use (`extended_kernel`).
    """
    size = geometry_size(geometry)
    max_radius = max(w.radius for w in geometry.wires)
    magnification = max(1.0, TARGET_WIRE_RADIUS_FRACTION * size / max_radius)
    draws = []
    for i, w in enumerate(geometry.wires):
        ratio = thin_wire.segment_to_radius_ratio(w)  # judged by the solver's own rules
        draws.append(
            WireDraw(
                w.start,
                w.end,
                w.radius,
                w.radius * magnification,
                i == geometry.feed_wire,
                ratio,
                thin_wire.wire_status(ratio, extended_kernel),
            )
        )
    return draws, magnification


WIRE_COLORS = {
    thin_wire.OK: "#b87333",  # copper
    thin_wire.STANDARD_OUT_OF_RANGE: "yellow",
    thin_wire.EXTENDED_OUT_OF_RANGE: "red",
}
FEED_COLOR = "dodgerblue"
_WIRE_LABELS = {
    thin_wire.OK: "wire: delta/a >= 8",
    thin_wire.STANDARD_OUT_OF_RANGE: "wire: delta/a < 8",
    thin_wire.EXTENDED_OUT_OF_RANGE: "wire: delta/a < 2",
}


def legend_entries(draws: list[WireDraw], extended_kernel: bool = False) -> list[tuple[str, str]]:
    """(label, colour) pairs for the wire categories present, plus the feed point."""
    present = {d.status for d in draws}
    labels = dict(_WIRE_LABELS)
    if extended_kernel:  # the extended kernel's limit (2) replaces the standard one (8)
        labels[thin_wire.OK] = "wire: delta/a >= 2"
    entries = [(labels[s], WIRE_COLORS[s]) for s in WIRE_COLORS if s in present]
    entries.append(("feed point", FEED_COLOR))
    return entries


def feed_point(geometry: Geometry) -> NDArray[np.float64]:
    """Centre of the driven segment (the middle segment of the fed wire)."""
    w = geometry.wires[geometry.feed_wire]
    segment = (w.segments + 1) // 2  # 1-based, same rule as Nec2Solver
    t = (segment - 0.5) / w.segments
    return np.asarray(w.start, dtype=float) * (1 - t) + np.asarray(w.end, dtype=float) * t


def pattern_surface(
    theta_rad: NDArray[np.float64],
    phi_rad: NDArray[np.float64],
    gain_dbi: NDArray[np.float64],
    max_radius: float,
    center: NDArray[np.float64] | None = None,
    dynamic_range_db: float = PATTERN_DYNAMIC_RANGE_DB,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Radiation-pattern surface as grids (X, Y, Z, gain) of shape (n_theta, n_phi + 1).

    The radius is proportional to gain above (peak - dynamic_range_db), so the peak has radius
    `max_radius` and anything at or below the floor (including exact nulls, -inf) collapses to
    the centre. `gain` is clipped to the same floor and is what the surface is coloured by.
    The phi seam is closed by repeating the first column.
    """
    peak = float(np.max(gain_dbi))
    floor = peak - dynamic_range_db
    g = np.clip(np.nan_to_num(gain_dbi, neginf=floor), floor, None)
    radius = max_radius * (g - floor) / (peak - floor)
    g = np.concatenate([g, g[:, :1]], axis=1)
    radius = np.concatenate([radius, radius[:, :1]], axis=1)
    phi = np.concatenate([phi_rad, [phi_rad[0] + 2 * np.pi]])
    th, ph = np.meshgrid(theta_rad, phi, indexing="ij")
    c = np.zeros(3) if center is None else np.asarray(center, dtype=float)
    x = c[0] + radius * np.sin(th) * np.cos(ph)
    y = c[1] + radius * np.sin(th) * np.sin(ph)
    z = c[2] + radius * np.cos(th)
    return x, y, z, g


# --- 2D plot -----------------------------------------------------------------------------


@dataclass(frozen=True)
class PatternCut:
    """A polar pattern cut. `angle_rad` runs clockwise from the top of the chart."""

    angle_rad: NDArray[np.float64]
    gain_dbi: NDArray[np.float64]  # -inf clipped to the floor
    title: str


def _floor(gain: NDArray[np.float64], dynamic_range_db: float) -> NDArray[np.float64]:
    floor = float(np.max(gain)) - dynamic_range_db
    return np.clip(np.nan_to_num(gain, neginf=floor), floor, None)


def horizontal_cut(
    result: Result, dynamic_range_db: float = PATTERN_DYNAMIC_RANGE_DB
) -> PatternCut:
    """Azimuth cut at the elevation closest to the horizon (theta = 90 deg).

    The angle is the azimuth phi, measured from +x towards +y.
    """
    gain = result.gain_dbi[0]
    it = int(np.argmin(np.abs(result.theta_rad - np.pi / 2)))
    ring = np.concatenate([gain[it], gain[it][:1]])
    phi = np.concatenate([result.phi_rad, [2 * np.pi]])
    floor_ref = _floor(gain, dynamic_range_db)  # same floor as the whole pattern
    floor = float(floor_ref.min())
    ring = np.clip(np.nan_to_num(ring, neginf=floor), floor, None)
    theta_deg = np.degrees(result.theta_rad[it])
    return PatternCut(
        phi,
        ring,
        f"Horizontal cut (theta = {theta_deg:.0f} deg)\n"
        "angle: azimuth, 0 = +x, clockwise towards +y",
    )


def vertical_cut(result: Result, dynamic_range_db: float = PATTERN_DYNAMIC_RANGE_DB) -> PatternCut:
    """Elevation cut in the vertical plane that contains the peak-gain direction.

    The chart angle alpha is 0 at the zenith (+z); the half plane holding the peak runs
    clockwise (alpha = theta) and the opposite half plane completes the circle
    (alpha = 360 deg - theta).
    """
    gain = result.gain_dbi[0]
    n_theta, n_phi = gain.shape
    _, ip = np.unravel_index(int(np.argmax(gain)), gain.shape)
    front = gain[:, ip]
    back = gain[::-1, (ip + n_phi // 2) % n_phi]  # theta from 180 down to 0 on the far side
    alpha = np.concatenate([result.theta_rad, 2 * np.pi - result.theta_rad[::-1][1:]])
    values = np.concatenate([front, back[1:]])
    floor = float(_floor(gain, dynamic_range_db).min())
    values = np.clip(np.nan_to_num(values, neginf=floor), floor, None)
    phi_deg = np.degrees(result.phi_rad[ip])
    return PatternCut(
        alpha,
        values,
        f"Vertical cut (phi = {phi_deg:.0f} / {phi_deg + 180:.0f} deg)\n"
        f"angle: from zenith (0 = +z), clockwise through the phi = {phi_deg:.0f} deg side",
    )
