"""3D viewer (pyvista): wires, radiation pattern and coordinate axes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from antennamax.core.units import hz_to_mhz
from antennamax.viz import require
from antennamax.viz.data import (
    FEED_COLOR,
    WIRE_COLORS,
    DesignRun,
    feed_points,
    geometry_center,
    geometry_size,
    legend_entries,
    pattern_surface,
    wire_draws,
)

PATTERN_CMAP = "viridis"
PATTERN_OPACITY = 0.35  # low enough to see the wires and the feed point through the surface
PATTERN_SIZE_FRACTION = 0.8  # peak radius of the pattern relative to the structure size


def _add_legend(
    plotter: Any, entries: list[tuple[str, str]], window_size, pixel_ratio: float = 1.0
) -> None:
    """Coloured legend lines under the info text (pyvista's legend widget clips long labels).

    `pixel_ratio` scales the pixel offsets on high-DPI screens (window_size is in device pixels).
    """
    top = window_size[1] - 75 * pixel_ratio
    for i, (label, color) in enumerate(entries):
        plotter.add_text(
            f"-- {label}",
            position=(10 * pixel_ratio, top - 18 * pixel_ratio * i),
            color=color,
            font_size=9,
        )


def build_scene(run: DesignRun, off_screen: bool = False, window_size=(1000, 800)) -> Any:
    """Create a pyvista Plotter holding the scene (not shown yet)."""
    pv = require("pyvista", "open the 3D view", extra="gui")
    plotter = pv.Plotter(off_screen=off_screen, window_size=list(window_size))
    populate_scene(plotter, run, window_size)
    return plotter


def populate_scene(
    plotter: Any, run: DesignRun, window_size=(1000, 800), pixel_ratio: float = 1.0
) -> None:
    """Draw the wires, the radiation pattern and the axes on a pyvista plotter.

    Works on any plotter (a plain Plotter, or the interactor embedded in the GUI).
    """
    pv = require("pyvista", "open the 3D view", extra="gui")
    geometry = run.geometry
    size = geometry_size(geometry)
    center = geometry_center(geometry)

    extended = bool(run.sweep_result.meta.get("extended_kernel"))
    draws, magnification = wire_draws(geometry, extended)
    for d in draws:
        line = pv.Line(d.start, d.end, resolution=1)
        plotter.add_mesh(
            line.tube(radius=d.display_radius, n_sides=16), color=WIRE_COLORS[d.status]
        )
    thickest = max(d.display_radius for d in draws)
    feed_radius = max(1.5 * thickest, min(4.0 * thickest, 0.02 * size))
    for point in feed_points(geometry):
        plotter.add_mesh(pv.Sphere(radius=feed_radius, center=point), color=FEED_COLOR)

    result = run.pattern_result
    x, y, z, gain = pattern_surface(
        result.theta_rad,
        result.phi_rad,
        result.gain_dbi[0],
        max_radius=PATTERN_SIZE_FRACTION * size,
        center=center,
    )
    surface = pv.StructuredGrid(x, y, z)
    surface["Gain [dBi]"] = gain.ravel(order="F")
    plotter.add_mesh(
        surface,
        scalars="Gain [dBi]",
        cmap=PATTERN_CMAP,
        opacity=PATTERN_OPACITY,
        scalar_bar_args={"title": "Gain [dBi]", "vertical": True},
    )

    plotter.add_axes(xlabel="x", ylabel="y", zlabel="z")
    plotter.show_bounds(
        grid=False,
        location="outer",
        xtitle="x [m]",
        ytitle="y [m]",
        ztitle="z [m]",
        font_size=10,
    )
    peak = float(np.max(result.gain_dbi))
    rule = "red < 2 (extended-kernel limit)" if extended else "yellow < 8, red < 2"
    plotter.add_text(
        f"{run.design.template_name}  {hz_to_mhz(run.center_frequency_hz):.3f} MHz  "
        f"peak {peak:.2f} dBi\n"
        f"wire radius drawn x{magnification:.1f}; "
        f"extended thin-wire kernel {'on' if extended else 'off'}\n"
        f"delta/a = segment length / radius: {rule}",
        font_size=9,
    )
    _add_legend(plotter, legend_entries(draws, extended), window_size, pixel_ratio)
    plotter.view_isometric()


def show(run: DesignRun, screenshot: Path | None = None) -> None:
    """Open the viewer window, or render off-screen to a PNG if `screenshot` is given."""
    if screenshot is not None:
        plotter = build_scene(run, off_screen=True)
        plotter.screenshot(str(screenshot))
        plotter.close()
    else:
        build_scene(run).show()
