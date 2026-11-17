"""2D summary plot (matplotlib): SWR, R/X versus frequency and two polar pattern cuts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from antennamax.core.units import hz_to_mhz
from antennamax.viz import require
from antennamax.viz.data import (
    PATTERN_DYNAMIC_RANGE_DB,
    DesignRun,
    PatternCut,
    horizontal_cut,
    vertical_cut,
)

SWR_PLOT_MAX = 10.0


def _polar(ax: Any, cut: PatternCut, peak: float, dynamic_range_db: float) -> None:
    ax.plot(cut.angle_rad, cut.gain_dbi)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_rlim(peak - dynamic_range_db, peak)
    ax.set_title(cut.title, fontsize=9, pad=12)
    ax.tick_params(labelsize=7)


def _swr_axes(ax: Any, run: DesignRun) -> None:
    result = run.sweep_result
    f_mhz = hz_to_mhz(result.frequencies_hz)
    swr = np.where(np.isfinite(result.swr), result.swr, SWR_PLOT_MAX)
    ax.plot(f_mhz, np.minimum(swr, SWR_PLOT_MAX), "o-")
    ax.axhline(2.0, color="gray", linestyle="--", linewidth=0.8)
    ax.axvline(hz_to_mhz(run.center_frequency_hz), color="gray", linestyle=":", linewidth=0.8)
    # Auto-scale to the data (at least up to SWR 3 so the 2:1 line stays visible).
    top = min(SWR_PLOT_MAX, max(3.0, float(np.max(np.minimum(swr, SWR_PLOT_MAX))) * 1.1))
    ax.set_ylim(1.0, top)
    ax.set_xlabel("Frequency [MHz]")
    ax.set_ylabel(f"SWR (Z0 = {result.z0:g} ohm)")
    ax.set_title("SWR")
    ax.grid(True, alpha=0.3)


def _impedance_axes(ax: Any, run: DesignRun) -> None:
    result = run.sweep_result
    f_mhz = hz_to_mhz(result.frequencies_hz)
    ax.plot(f_mhz, result.impedance.real, "o-", label="R")
    ax.plot(f_mhz, result.impedance.imag, "s-", label="X")
    ax.axhline(0.0, color="gray", linewidth=0.8)
    ax.axvline(hz_to_mhz(run.center_frequency_hz), color="gray", linestyle=":", linewidth=0.8)
    ax.set_xlabel("Frequency [MHz]")
    ax.set_ylabel("Impedance [ohm]")
    ax.set_title("Input impedance")
    ax.legend()
    ax.grid(True, alpha=0.3)


def _pattern_axes(fig: Any, run: DesignRun, specs: Any) -> float:
    """The horizontal and vertical cuts on two polar axes; returns the peak gain [dBi]."""
    pattern = run.pattern_result
    peak = float(np.max(pattern.gain_dbi))
    for spec, cut in zip(specs, (horizontal_cut(pattern), vertical_cut(pattern)), strict=True):
        _polar(fig.add_subplot(spec, projection="polar"), cut, peak, PATTERN_DYNAMIC_RANGE_DB)
    return peak


def draw_impedance(run: DesignRun, fig: Any) -> None:
    """SWR and R/X versus frequency, side by side."""
    gs = fig.add_gridspec(1, 2)
    _swr_axes(fig.add_subplot(gs[0, 0]), run)
    _impedance_axes(fig.add_subplot(gs[0, 1]), run)
    fig.tight_layout()


def draw_patterns(run: DesignRun, fig: Any) -> None:
    """The horizontal-plane and vertical-plane pattern cuts, side by side (polar)."""
    f0_mhz = hz_to_mhz(run.center_frequency_hz)
    gs = fig.add_gridspec(1, 2)
    peak = _pattern_axes(fig, run, (gs[0, 0], gs[0, 1]))
    fig.suptitle(
        f"{run.design.template_name}: patterns at {f0_mhz:.3f} MHz (peak {peak:.2f} dBi)",
        fontsize=11,
    )
    fig.tight_layout()


def draw(run: DesignRun, fig: Any) -> None:
    """Draw the 2x2 summary onto a matplotlib Figure."""
    f0_mhz = hz_to_mhz(run.center_frequency_hz)
    gs = fig.add_gridspec(2, 2)
    _swr_axes(fig.add_subplot(gs[0, 0]), run)
    _impedance_axes(fig.add_subplot(gs[0, 1]), run)
    peak = _pattern_axes(fig, run, (gs[1, 0], gs[1, 1]))
    fig.suptitle(
        f"{run.design.template_name}: patterns at {f0_mhz:.3f} MHz (peak {peak:.2f} dBi)",
        fontsize=11,
    )
    fig.tight_layout()


def save(run: DesignRun, path: Path) -> None:
    """Render the summary to a PNG file without opening a window."""
    figure_mod = require("matplotlib.figure", "draw the summary plot", extra="plot")
    fig = figure_mod.Figure(figsize=(10, 8), dpi=120)
    draw(run, fig)
    fig.savefig(path, format="png")


def show(run: DesignRun) -> None:
    """Open the summary in a matplotlib window."""
    plt = require("matplotlib.pyplot", "draw the summary plot", extra="plot")
    fig = plt.figure(figsize=(10, 8))
    draw(run, fig)
    plt.show()
