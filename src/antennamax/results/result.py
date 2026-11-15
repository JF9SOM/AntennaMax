"""Result type returned by all solvers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray


@dataclass
class Result:
    """Simulation result (SI units; angles in rad).

    `gain_dbi` has shape (n_freq, n_theta, n_phi), or is None if no pattern was computed.
    theta is measured from +z; phi from +x towards +y. Exact nulls are -inf.
    """

    frequencies_hz: NDArray[np.float64]
    impedance: NDArray[np.complex128]
    z0: float = 50.0
    theta_rad: NDArray[np.float64] | None = None
    phi_rad: NDArray[np.float64] | None = None
    gain_dbi: NDArray[np.float64] | None = None

    def __post_init__(self) -> None:
        self.frequencies_hz = np.asarray(self.frequencies_hz, dtype=float)
        self.impedance = np.asarray(self.impedance, dtype=complex)
        if self.frequencies_hz.shape != self.impedance.shape:
            raise ValueError("frequencies_hz and impedance must have the same shape")
        if self.z0 <= 0:
            raise ValueError("z0 must be positive")
        if self.gain_dbi is not None:
            if self.theta_rad is None or self.phi_rad is None:
                raise ValueError("gain_dbi requires theta_rad and phi_rad")
            self.gain_dbi = np.asarray(self.gain_dbi, dtype=float)
            expected = (len(self.frequencies_hz), len(self.theta_rad), len(self.phi_rad))
            if self.gain_dbi.shape != expected:
                raise ValueError(f"gain_dbi shape {self.gain_dbi.shape} != {expected}")

    @property
    def reflection_coefficient(self) -> NDArray[np.complex128]:
        return (self.impedance - self.z0) / (self.impedance + self.z0)

    @property
    def swr(self) -> NDArray[np.float64]:
        """VSWR at each frequency (inf for total reflection, |Γ| >= 1 - 1e-12)."""
        gamma = np.abs(self.reflection_coefficient)
        total = gamma >= 1.0 - 1e-12
        safe = np.where(total, 0.0, gamma)
        return np.where(total, np.inf, (1.0 + safe) / (1.0 - safe))

    def _max_gain_indices(self) -> tuple[NDArray[np.intp], NDArray[np.intp], NDArray[np.intp]]:
        if self.gain_dbi is None or self.theta_rad is None or self.phi_rad is None:
            raise ValueError("radiation pattern was not computed")
        n_freq, n_theta, n_phi = self.gain_dbi.shape
        flat = self.gain_dbi.reshape(n_freq, -1).argmax(axis=1)
        it, ip = np.divmod(flat, n_phi)
        return np.arange(n_freq), it, ip

    @property
    def max_gain_dbi(self) -> NDArray[np.float64]:
        """Peak gain at each frequency (requires the full pattern)."""
        f, it, ip = self._max_gain_indices()
        return self.gain_dbi[f, it, ip]

    @property
    def max_gain_direction_rad(self) -> NDArray[np.float64]:
        """(theta, phi) of the peak gain at each frequency, shape (n_freq, 2)."""
        _, it, ip = self._max_gain_indices()
        return np.stack([self.theta_rad[it], self.phi_rad[ip]], axis=1)

    @property
    def front_to_back_db(self) -> NDArray[np.float64]:
        """Peak gain minus gain in the exactly opposite direction, per frequency [dB].

        Requires the full-sphere pattern on a grid that contains the opposite point
        (theta -> pi - theta, phi -> phi + pi), which holds when the grid step divides
        180 deg. Returns +inf if the opposite direction is an exact null.
        """
        f, it, ip = self._max_gain_indices()
        n_theta, n_phi = self.gain_dbi.shape[1:]
        if n_phi % 2 != 0:
            raise ValueError("pattern grid has no exactly opposite direction")
        back = self.gain_dbi[f, n_theta - 1 - it, (ip + n_phi // 2) % n_phi]
        with np.errstate(invalid="ignore"):
            return self.gain_dbi[f, it, ip] - back

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable form. Non-finite values (inf SWR, -inf gain nulls, inf F/B)
        become None because JSON has no infinity."""
        d: dict[str, Any] = {
            "frequencies_hz": self.frequencies_hz.tolist(),
            "z0": self.z0,
            "impedance_real": self.impedance.real.tolist(),
            "impedance_imag": self.impedance.imag.tolist(),
            "swr": _json_safe(self.swr),
            "theta_rad": None,
            "phi_rad": None,
            "gain_dbi": None,
            "max_gain_dbi": None,
            "front_to_back_db": None,
        }
        if self.gain_dbi is not None:
            d["theta_rad"] = self.theta_rad.tolist()
            d["phi_rad"] = self.phi_rad.tolist()
            d["gain_dbi"] = _json_safe(self.gain_dbi)
            d["max_gain_dbi"] = _json_safe(self.max_gain_dbi)
            d["front_to_back_db"] = _json_safe(self.front_to_back_db)
        return d


def _json_safe(a: NDArray[np.float64]) -> Any:
    """Nested lists with non-finite values replaced by None."""
    return _nan_to_none(a.tolist())


def _nan_to_none(x: Any) -> Any:
    if isinstance(x, list):
        return [_nan_to_none(v) for v in x]
    return x if math.isfinite(x) else None
