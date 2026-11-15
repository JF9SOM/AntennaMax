"""Result type returned by all solvers."""

from __future__ import annotations

from dataclasses import dataclass

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
