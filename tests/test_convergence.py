"""Segment-count convergence of the NEC2 dipole impedance (Omega=12.5, beta*h=1.6).

Only segment counts that satisfy the NEC2 standard-kernel guideline Delta/a >= 8 are tested.
For Omega = 12.5, Delta/a = e^6.25 / N = 518.0 / N, so N <= 64. Larger N (81, 101: Delta/a of
6.4 and 5.1) are outside the guideline and drift; they are only reported, not asserted.
"""

from test_king_middleton import MIN_SEGMENT_TO_RADIUS, nec2_impedance, segment_to_radius

OMEGA = 12.5
SEGMENT_COUNTS = (21, 31, 45, 61)
MAX_CHANGE_OHM = 1.0  # fixed a priori; do not widen to make the test pass


def test_segment_counts_respect_the_thin_wire_guideline():
    for n in SEGMENT_COUNTS:
        assert segment_to_radius(OMEGA, n) >= MIN_SEGMENT_TO_RADIUS


def test_impedance_converges_with_segment_count():
    zs = [nec2_impedance(OMEGA, 1.6, segments=n) for n in SEGMENT_COUNTS]
    pairs = list(zip(SEGMENT_COUNTS, zs, strict=True))
    for (n0, z0), (n1, z1) in zip(pairs, pairs[1:], strict=False):
        assert abs(z1.real - z0.real) < MAX_CHANGE_OHM, (
            f"R {n0}->{n1}: {z0.real:.3f}->{z1.real:.3f}"
        )
        assert abs(z1.imag - z0.imag) < MAX_CHANGE_OHM, (
            f"X {n0}->{n1}: {z0.imag:.3f}->{z1.imag:.3f}"
        )
