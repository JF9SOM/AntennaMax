"""Quadrifilar helix (QFH) template: dimensions after Coppens (ON6JC) and a NEC2 wire model.

Dimension formulas: the re-implementation by KF8EEZ,
  https://kf8eez.github.io/qfh-antenna/static/verify.html
of Coppens' calculator, https://www.jcoppens.com/ant/qfh/calc.en.php. The formulas below were
transcribed from that re-implementation page; they have NOT been compared directly with
Coppens' original page. Lengths are in metres.

  wavelength             lambda   = c / f
  compensated wavelength lambda_c = lambda * delta(d_eff),  d_eff = min(d, 15 mm),
                         delta = linear interpolation in a table indexed by whole mm
  bend correction        bcorr    = 2 R - pi R / 2                       (per 90 degree bend)
  large loop             L1  = 1.026 * lambda_c   (small loop: L2 = 0.975 * lambda_c)
  compensated length     Lc  = L + 4 bcorr
  horizontal separator   D   = 0.5 * Lc / (1 + sqrt(1 / r^2 + (N pi)^2)),  r = width/height
  compensated horizontal Dc  = D - 2 R
  vertical (helix arm)   V   = (Lc - 2 D) / 2,   compensated Vc = V - 2 R
  height                 H   = D / r

Geometry of one loop: a bottom horizontal of length D, two helical arms (radius D/2, rising by
H while turning through 2 pi N), and a top horizontal of length D split at the axis. The path
length of the sharp-cornered model equals Lc (2 D + 2 V).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from pydantic import NonNegativeFloat, PositiveFloat, PositiveInt, model_validator

from antennamax.core.geometry import Feed, Geometry, Wire
from antennamax.core.segmentation import DEFAULT_SEGMENTS_PER_WAVELENGTH, choose_segments
from antennamax.templates.base import Template

SPEED_OF_LIGHT = 299_792_458.0  # m/s
COPPENS_SPEED_OF_LIGHT = 3.0e8  # m/s, as used by the original calculator (and the KF8EEZ page)

# Correction factor delta(d) by whole millimetre of conductor diameter, 0..16 mm
# (KF8EEZ re-implementation of Coppens' table). The diameter is capped at 15 mm before lookup.
# TODO(要確認): 原典(Coppens のページ)の表との直接照合は未実施。
_DELTA_TABLE = (
    1.045, 1.053, 1.060, 1.064, 1.068, 1.070, 1.070, 1.071, 1.071,
    1.070, 1.070, 1.070, 1.070, 1.069, 1.069, 1.068, 1.067,
)  # fmt: skip
_MAX_EFFECTIVE_DIAMETER_MM = 15.0

LARGE_LOOP_FACTOR = 1.026  # loop length / compensated wavelength
SMALL_LOOP_FACTOR = 0.975

# The feed is a short wire at the top; its length in conductor radii (its single segment must
# keep delta/a clear of the thin-wire limits).
FEED_GAP_RADII = 10.0


def wire_correction_factor(diameter_m: float) -> float:
    """delta(d): table lookup with linear interpolation (diameter capped at 15 mm)."""
    d_mm = min(diameter_m * 1000.0, _MAX_EFFECTIVE_DIAMETER_MM)
    i = math.floor(d_mm)
    return _DELTA_TABLE[i] + (_DELTA_TABLE[i + 1] - _DELTA_TABLE[i]) * (d_mm - i)


@dataclass(frozen=True)
class QfhLoopDimensions:
    total_length_m: float  # L
    compensated_length_m: float  # Lc = L + 4 bcorr
    horizontal_m: float  # D
    compensated_horizontal_m: float  # Dc = D - 2R
    vertical_m: float  # V, the helix arm length
    compensated_vertical_m: float  # Vc = V - 2R
    height_m: float  # H = D / r


@dataclass(frozen=True)
class QfhDimensions:
    wavelength_m: float
    compensated_wavelength_m: float
    bend_correction_m: float
    large: QfhLoopDimensions
    small: QfhLoopDimensions


class Qfh(Template):
    """Quadrifilar helix antenna (free space), axis along +z, feed at the top.

    Winding and polarisation (feed at the top, radiation towards +z, the zenith):
    `handedness="left"` radiates RHCP and `"right"` radiates LHCP. The winding sense is opposite
    to the polarisation sense for this backfire arrangement (feed at the top). Sources:
    AN-SOF, https://antennasimulator.com/index.php/2022/11/22/qfh-antenna-for-noaa-satellite-reception/
    (left-handed helices give RHCP; backfire configuration with the feed at the top), and the
    AMSAT-BB thread https://mailman.amsat.org/hyperkitty/list/amsat-bb@amsat.org/thread/LP3UGHL23MQEGJK57YOLFTRLC2BFH6RJ
    (cited as given; the page could not be retrieved here). The NEC2 model agrees
    (tests/test_qfh.py). The default is therefore "left", the winding for RHCP.
    """

    center_frequency_hz: PositiveFloat
    turns: PositiveFloat = 0.5
    diameter_m: PositiveFloat  # conductor diameter
    bend_radius_m: NonNegativeFloat
    width_height_ratio: PositiveFloat = 0.44
    handedness: Literal["right", "left"] = "left"  # left = RHCP towards +z (feed at the top)
    # Coppens' original calculator uses 3e8 m/s; set speed_of_light_m_s=COPPENS_SPEED_OF_LIGHT
    # to reproduce it.
    speed_of_light_m_s: PositiveFloat = SPEED_OF_LIGHT
    segments_per_wavelength: PositiveFloat = DEFAULT_SEGMENTS_PER_WAVELENGTH
    max_frequency_hz: PositiveFloat | None = None  # top of the sweep; default: centre frequency
    helix_pieces_per_turn: PositiveInt = 24  # straight pieces approximating each helix arm

    @model_validator(mode="after")
    def _check(self) -> Qfh:
        if self.helix_pieces_per_turn < 4:
            raise ValueError("helix_pieces_per_turn must be at least 4")
        if self.max_frequency_hz is not None and self.max_frequency_hz < self.center_frequency_hz:
            raise ValueError("max_frequency_hz must not be below the centre frequency")
        if self.dimensions.small.compensated_horizontal_m <= 0:
            raise ValueError("bend_radius_m is too large for the loop size (Dc <= 0)")
        return self

    # --- dimensions ----------------------------------------------------------------------

    def _loop(
        self, factor: float, compensated_wavelength: float, bcorr: float
    ) -> QfhLoopDimensions:
        r = self.width_height_ratio
        total = factor * compensated_wavelength
        compensated = total + 4.0 * bcorr
        d = 0.5 * compensated / (1.0 + math.sqrt(1.0 / r**2 + (self.turns * math.pi) ** 2))
        v = (compensated - 2.0 * d) / 2.0
        two_r = 2.0 * self.bend_radius_m
        return QfhLoopDimensions(total, compensated, d, d - two_r, v, v - two_r, d / r)

    @property
    def dimensions(self) -> QfhDimensions:
        wavelength = self.speed_of_light_m_s / self.center_frequency_hz
        compensated_wavelength = wavelength * wire_correction_factor(self.diameter_m)
        radius = self.bend_radius_m
        bcorr = 2.0 * radius - math.pi * radius / 2.0
        return QfhDimensions(
            wavelength,
            compensated_wavelength,
            bcorr,
            self._loop(LARGE_LOOP_FACTOR, compensated_wavelength, bcorr),
            self._loop(SMALL_LOOP_FACTOR, compensated_wavelength, bcorr),
        )

    # --- NEC2 model ----------------------------------------------------------------------

    def to_geometry(self) -> Geometry:
        """Two bifilar loops (large, small) fed in parallel at the top.

        TODO(要確認): 曲げ半径は形状に反映していない(角は直角、経路長は補正後全長 Lc に等しい)。
        Small loop: turned -90 degrees (right winding) or +90 degrees (left) from the large loop,
        and connected to the feed terminals the other way round (arm 0 to terminal 2). The
        large loop is longer than resonance (current lags), the small loop shorter (current
        leads); the quadrature phasing needs this orientation AND this feed polarity.

        Feed polarity fix: the first version connected the small loop like the large one. The NEC2
        check then showed the beam and the good circular polarisation pointing straight down
        (nadir axial ratio 0.90 / 0.39 dB at 137.5 / 435 MHz, peak gain at theta = 180 degrees)
        instead of up, i.e. the small loop's feed polarity was reversed. This is a correction of
        that wiring error, not a relaxation of any acceptance criterion (docs/VERIFICATION.md).
        """
        dims = self.dimensions
        fmax = self.max_frequency_hz or self.center_frequency_hz
        radius = self.diameter_m / 2.0
        sense = 1.0 if self.handedness == "right" else -1.0
        gap = FEED_GAP_RADII * radius
        top_z = dims.large.height_m  # the loops are aligned at the top, where the feed is
        t1 = (0.0, 0.0, top_z)  # feed terminal 1
        t2 = (0.0, 0.0, top_z + gap)  # feed terminal 2
        wires: list[Wire] = []

        def add(start, end, odd=False):
            length = math.dist(start, end)
            n = choose_segments(length, radius, fmax, self.segments_per_wavelength, odd=odd)
            wires.append(Wire(tuple(start), tuple(end), radius, n.segments))

        def add_loop(loop: QfhLoopDimensions, angle0: float, swap_terminals: bool) -> None:
            first, second = (t2, t1) if swap_terminals else (t1, t2)
            r = loop.horizontal_m / 2.0
            z0 = top_z - loop.height_m
            pieces = max(2, math.ceil(self.helix_pieces_per_turn * self.turns))
            twist = sense * 2.0 * math.pi * self.turns

            def point(arm: int, i: int):
                a = angle0 + math.pi * arm + twist * i / pieces
                return (r * math.cos(a), r * math.sin(a), z0 + loop.height_m * i / pieces)

            add(point(0, 0), point(1, 0))  # bottom horizontal, a diameter
            for arm in (0, 1):  # helical arms as polylines
                for i in range(pieces):
                    add(point(arm, i), point(arm, i + 1))
            add(point(0, pieces), first)  # top horizontal, split at the axis
            add(point(1, pieces), second)

        add_loop(dims.large, 0.0, swap_terminals=False)
        add_loop(dims.small, -sense * math.pi / 2.0, swap_terminals=True)
        feed_index = len(wires)
        add(t1, t2, odd=True)  # the short feed wire carries the single voltage source
        return Geometry(wires, feeds=[Feed(feed_index)])
