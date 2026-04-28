from __future__ import annotations
import re


def natural_sort_key(s: str):
    """Sort strings containing numbers in a human-friendly (natural) sort order."""
    return [
        int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", s)
    ]


def _lerp(y0: float, y1: float, x0: int, x1: int, x: int) -> float:
    if x1 == x0:
        return float(y0)
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def interpolate_scaling(xs: list[int], ys: list[int], luma: int) -> float:
    if not xs:
        return 0.0
    if luma <= xs[0]:
        return float(ys[0])
    if luma >= xs[-1]:
        return float(ys[-1])
    for i in range(len(xs) - 1):
        if xs[i] <= luma <= xs[i + 1]:
            return _lerp(ys[i], ys[i + 1], xs[i], xs[i + 1], luma)
    return 0.0


def _clip3(lo: int, hi: int, val: int) -> int:
    return max(lo, min(hi, val))


def _parse_grain_size(grain_size) -> int:
    try:
        return int(grain_size)
    except (ValueError, TypeError):
        import re

        m = re.search(r"\d+", str(grain_size))
        if m:
            return int(m.group(0))
        return -1  # Default to -1 (Manual/Original) if no digits found


def validate_fgs_pipeline(
    coeffs: list[int],
    ar_shift: int,
    curve_points_y: list[int],
) -> list[str]:

    warnings = []

    if len(curve_points_y) < 2:
        return warnings

    if coeffs:
        # Check algebraic sum (DC stability)
        total_sum = sum(coeffs)
        max_allowed = 1 << ar_shift

        if total_sum >= max_allowed:
            warnings.append(
                f"AR_MATH_ERROR: The algebraic sum of the coefficients ({total_sum}) "
                f"exceeds or equals the divisor ({max_allowed}). Calculated energy "
                "would be negative and the preview cannot be computed."
            )

    if curve_points_y:
        max_curve_val = max(curve_points_y)
        if max_curve_val > 255:
            warnings.append(
                f"CURVE_CLIPPING: The curve reaches {max_curve_val}. "
                "The maximum allowed is 255, so the curve shape will be clipped. "
                "Reduce the curve values."
            )

    return warnings


def get_chroma_scaling_index(
    luma_val: int, chroma_val: int, mult: int, luma_mult: int, offset: int
) -> int:
    combined = luma_val * (luma_mult - 128) + chroma_val * (mult - 128)
    index = (combined >> 6) + (offset - 256)
    return max(0, min(255, index))


def build_chroma_deterministic_curve(
    sC_xs: list[int],
    sC_ys: list[int],
    block_min: int,
    block_max: int,
    scaling_shift: int,
    mult: int,
    luma_mult: int,
    offset: int,
    chroma_scaling_from_luma: bool,
    ch_range: range = range(0, 256),
) -> tuple[list[int], list[float], list[float]]:
    """
    Compute the maximum excursions (delta_min, delta_max) for Chroma,
    evaluating the worst-case scenario derived from the Luma/Chroma intersection.

    Returns:
        (ch_vals, min_amps_8bit, max_amps_8bit)
    """
    ch_vals = list(ch_range)
    min_amps: list[float] = []
    max_amps: list[float] = []

    if not sC_xs or not sC_ys:
        return ch_vals, [0.0] * 256, [0.0] * 256

    total_shift = scaling_shift + 4
    divisor = 1 << total_shift

    for c_val in ch_vals:
        worst_case_force = 0

        if chroma_scaling_from_luma:
            for l_val in range(256):
                force = interpolate_scaling(sC_xs, sC_ys, l_val)
                if force > worst_case_force:
                    worst_case_force = force
        else:
            for l_val in range(256):
                idx = get_chroma_scaling_index(l_val, c_val, mult, luma_mult, offset)
                force = interpolate_scaling(sC_xs, sC_ys, idx)
                if force > worst_case_force:
                    worst_case_force = force

        d_min = (block_min * worst_case_force) / divisor
        d_max = (block_max * worst_case_force) / divisor

        min_amps.append(d_min)
        max_amps.append(d_max)

    return ch_vals, min_amps, max_amps
