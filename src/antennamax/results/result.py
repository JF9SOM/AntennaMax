"""Result type returned by all solvers."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
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
    # Input impedance of the FIRST source (feed 0), shape (n_freq,). `swr` and
    # `reflection_coefficient` are also based on it. With several sources see `feed_impedances`.
    impedance: NDArray[np.complex128]
    z0: float = 50.0
    theta_rad: NDArray[np.float64] | None = None
    phi_rad: NDArray[np.float64] | None = None
    gain_dbi: NDArray[np.float64] | None = None
    # Complex far-field components, same shape as gain_dbi, in the solver's own scale (only the
    # ratios between components and directions are used). Needed for circular polarisation.
    e_theta: NDArray[np.complex128] | None = None
    e_phi: NDArray[np.complex128] | None = None
    # Input impedance of every source, shape (n_freq, n_feeds), in the order of the sources;
    # column 0 equals `impedance`. Defaults to that single column.
    feed_impedances: NDArray[np.complex128] | None = None
    # Solver information, e.g. {"solver": "nec2", "extended_kernel": True, ...}.
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.frequencies_hz = np.asarray(self.frequencies_hz, dtype=float)
        self.impedance = np.asarray(self.impedance, dtype=complex)
        if self.frequencies_hz.shape != self.impedance.shape:
            raise ValueError("frequencies_hz and impedance must have the same shape")
        if self.z0 <= 0:
            raise ValueError("z0 must be positive")
        if self.feed_impedances is None:
            self.feed_impedances = self.impedance[:, np.newaxis]
        else:
            self.feed_impedances = np.asarray(self.feed_impedances, dtype=complex)
            if (
                self.feed_impedances.ndim != 2
                or self.feed_impedances.shape[0] != len(self.frequencies_hz)
                or self.feed_impedances.shape[1] < 1
            ):
                raise ValueError("feed_impedances must have shape (n_freq, n_feeds)")
        if self.gain_dbi is not None:
            if self.theta_rad is None or self.phi_rad is None:
                raise ValueError("gain_dbi requires theta_rad and phi_rad")
            self.gain_dbi = np.asarray(self.gain_dbi, dtype=float)
            expected = (len(self.frequencies_hz), len(self.theta_rad), len(self.phi_rad))
            if self.gain_dbi.shape != expected:
                raise ValueError(f"gain_dbi shape {self.gain_dbi.shape} != {expected}")
        if (self.e_theta is None) != (self.e_phi is None):
            raise ValueError("e_theta and e_phi must be given together")
        if self.e_theta is not None:
            if self.gain_dbi is None:
                raise ValueError("e_theta/e_phi require gain_dbi")
            self.e_theta = np.asarray(self.e_theta, dtype=complex)
            self.e_phi = np.asarray(self.e_phi, dtype=complex)
            if self.e_theta.shape != self.gain_dbi.shape or self.e_phi.shape != self.e_theta.shape:
                raise ValueError("e_theta and e_phi must have the shape of gain_dbi")

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

    # --- circular polarisation -------------------------------------------------------------
    #
    # TODO(要確認): 符号規約。時間依存は e^{j omega t}(NEC2 と同じ)、波は +r 方向に進むとし、
    # IEEE の右旋円偏波(RHCP: 進行方向に親指を向けて指が回る向き。e^{jwt} では +z へ進む波で
    # E ∝ x^ - j y^)に対して E_R = (E_theta + j E_phi)/sqrt(2)、E_L = (E_theta - j E_phi)/sqrt(2)。
    # ターンスタイル(y 側を 90 度遅らせる → +z で RHCP)で PyNEC 2.4.0 と整合することを
    # tests/test_polarization.py で確認済みだが、独立エンジン・実測との照合は未実施
    # (docs/VERIFICATION.md 参照)。

    def _circular_powers(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """|E_R|^2 and |E_L|^2 (solver scale); |E_R|^2 + |E_L|^2 = |E_theta|^2 + |E_phi|^2."""
        if self.e_theta is None or self.e_phi is None:
            raise ValueError("far-field components were not computed")
        e_r = (self.e_theta + 1j * self.e_phi) / math.sqrt(2.0)
        e_l = (self.e_theta - 1j * self.e_phi) / math.sqrt(2.0)
        return np.abs(e_r) ** 2, np.abs(e_l) ** 2

    def _circular_gain_dbic(self, power: NDArray[np.float64]) -> NDArray[np.float64]:
        """Total gain scaled by this component's share of the radiated power density."""
        p_r, p_l = self._circular_powers()
        total = p_r + p_l
        with np.errstate(divide="ignore", invalid="ignore"):
            share = np.where(total > 0, power / total, 0.0)
            return self.gain_dbi + 10.0 * np.log10(share)  # log10(0) = -inf

    @property
    def rhcp_gain_dbic(self) -> NDArray[np.float64]:
        """Right-hand circularly polarised gain [dBic], shape (n_freq, n_theta, n_phi)."""
        return self._circular_gain_dbic(self._circular_powers()[0])

    @property
    def lhcp_gain_dbic(self) -> NDArray[np.float64]:
        """Left-hand circularly polarised gain [dBic], shape (n_freq, n_theta, n_phi)."""
        return self._circular_gain_dbic(self._circular_powers()[1])

    @property
    def axial_ratio_db(self) -> NDArray[np.float64]:
        """Axial ratio [dB] in every direction: 0 dB circular, inf linear, nan where no field.

        AR = (|E_R| + |E_L|) / ||E_R| - |E_L||. Differences below 1e-9 of the sum count as
        exactly linear (inf).
        """
        p_r, p_l = self._circular_powers()
        e_r, e_l = np.sqrt(p_r), np.sqrt(p_l)
        total = e_r + e_l
        with np.errstate(divide="ignore", invalid="ignore"):
            minor_share = np.abs(e_r - e_l) / total  # 1/AR, in 0..1
            ar = np.where(minor_share < 1e-9, np.inf, -20.0 * np.log10(minor_share))
        return np.where(total > 0, ar, np.nan)

    @property
    def zenith_axial_ratio_db(self) -> NDArray[np.float64]:
        """Axial ratio towards +z (theta = 0) at each frequency [dB]."""
        return self.axial_ratio_db[:, 0, 0]

    @property
    def zenith_rhcp_gain_dbic(self) -> NDArray[np.float64]:
        return self.rhcp_gain_dbic[:, 0, 0]

    @property
    def zenith_lhcp_gain_dbic(self) -> NDArray[np.float64]:
        return self.lhcp_gain_dbic[:, 0, 0]

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable form. Non-finite values (inf SWR, -inf gain nulls, inf F/B)
        become None because JSON has no infinity."""
        d: dict[str, Any] = {
            "frequencies_hz": self.frequencies_hz.tolist(),
            "z0": self.z0,
            "impedance_real": self.impedance.real.tolist(),
            "impedance_imag": self.impedance.imag.tolist(),
            "feed_impedances_real": self.feed_impedances.real.tolist(),
            "feed_impedances_imag": self.feed_impedances.imag.tolist(),
            "swr": _json_safe(self.swr),
            "theta_rad": None,
            "phi_rad": None,
            "gain_dbi": None,
            "max_gain_dbi": None,
            "front_to_back_db": None,
            "zenith_axial_ratio_db": None,
            "zenith_rhcp_gain_dbic": None,
            "zenith_lhcp_gain_dbic": None,
            "meta": dict(self.meta),
        }
        if self.gain_dbi is not None:
            d["theta_rad"] = self.theta_rad.tolist()
            d["phi_rad"] = self.phi_rad.tolist()
            d["gain_dbi"] = _json_safe(self.gain_dbi)
            d["max_gain_dbi"] = _json_safe(self.max_gain_dbi)
            d["front_to_back_db"] = _json_safe(self.front_to_back_db)
            if self.e_theta is not None:
                d["zenith_axial_ratio_db"] = _json_safe(self.zenith_axial_ratio_db)
                d["zenith_rhcp_gain_dbic"] = _json_safe(self.zenith_rhcp_gain_dbic)
                d["zenith_lhcp_gain_dbic"] = _json_safe(self.zenith_lhcp_gain_dbic)
        return d


def _json_safe(a: NDArray[np.float64]) -> Any:
    """Nested lists with non-finite values replaced by None."""
    return _nan_to_none(a.tolist())


def _nan_to_none(x: Any) -> Any:
    if isinstance(x, list):
        return [_nan_to_none(v) for v in x]
    return x if math.isfinite(x) else None
