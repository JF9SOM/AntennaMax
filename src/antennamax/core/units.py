"""Unit conversions. Internal units are SI (m, Hz, rad); convert only at I/O boundaries."""

from __future__ import annotations

import math


def mm_to_m(value_mm: float) -> float:
    return value_mm / 1000.0


def m_to_mm(value_m: float) -> float:
    return value_m * 1000.0


def mhz_to_hz(value_mhz: float) -> float:
    return value_mhz * 1.0e6


def hz_to_mhz(value_hz: float) -> float:
    return value_hz / 1.0e6


def deg_to_rad(value_deg: float) -> float:
    return math.radians(value_deg)


def rad_to_deg(value_rad: float) -> float:
    return math.degrees(value_rad)
