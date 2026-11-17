"""Text of the result summary (no GUI toolkit): built from the Result properties, nothing is
recomputed here."""

from __future__ import annotations

import math

import numpy as np

from antennamax.core.units import hz_to_mhz, rad_to_deg
from antennamax.viz.data import DesignRun

SWEEP_COLUMNS = ("f [MHz]", "R [ohm]", "X [ohm]", "SWR")


def _num(value: float, digits: int = 2) -> str:
    if math.isnan(value):
        return "n/a"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return f"{value:.{digits}f}"


def sweep_rows(run: DesignRun) -> list[tuple[str, ...]]:
    """One row per sweep frequency: frequency, R, X and SWR."""
    result = run.sweep_result
    return [
        (
            f"{hz_to_mhz(f):.3f}",
            _num(float(z.real)),
            _num(float(z.imag)),
            _num(float(swr)),
        )
        for f, z, swr in zip(result.frequencies_hz, result.impedance, result.swr, strict=True)
    ]


def center_summary(run: DesignRun) -> list[tuple[str, str]]:
    """(label, value) pairs for the design (centre) frequency, where the pattern is computed."""
    r = run.pattern_result
    z = complex(r.impedance[0])
    theta, phi = r.max_gain_direction_rad[0]
    meta = r.meta
    rows = [
        ("Centre frequency", f"{hz_to_mhz(run.center_frequency_hz):.3f} MHz"),
        (
            "Input impedance Z",
            f"{_num(z.real)} {'+' if z.imag >= 0 else '-'} j{_num(abs(z.imag))} ohm",
        ),
        (f"SWR (Z0 = {r.z0:g} ohm)", _num(float(r.swr[0]))),
        ("Maximum gain", f"{_num(float(r.max_gain_dbi[0]))} dBi"),
        (
            "Direction of maximum gain",
            f"theta {_num(rad_to_deg(theta), 0)} deg, phi {_num(rad_to_deg(phi), 0)} deg",
        ),
        ("Front-to-back ratio", f"{_num(float(r.front_to_back_db[0]))} dB"),
        ("Axial ratio at the zenith", f"{_num(float(r.zenith_axial_ratio_db[0]))} dB"),
        ("RHCP gain at the zenith", f"{_num(float(r.zenith_rhcp_gain_dbic[0]))} dBic"),
        ("LHCP gain at the zenith", f"{_num(float(r.zenith_lhcp_gain_dbic[0]))} dBic"),
    ]
    if "extended_kernel" in meta:
        kernel = "on" if meta["extended_kernel"] else "off"
        ratio = meta.get("min_segment_to_radius")
        rows.append(
            (
                "Extended thin-wire kernel",
                f"{kernel} (smallest segment / radius {_num(float(ratio), 1)})"
                if ratio is not None
                else kernel,
            )
        )
    sources = int(meta.get("n_feeds", 1))
    if sources > 1:
        rows.append(("Sources", f"{sources} (Z and SWR are those of the first)"))
    return rows


def pattern_extremes(run: DesignRun) -> tuple[float, float]:
    """Highest and lowest finite gain of the pattern [dBi] (for a status line)."""
    gain = run.pattern_result.gain_dbi
    finite = gain[np.isfinite(gain)]
    return float(finite.max()), float(finite.min())
