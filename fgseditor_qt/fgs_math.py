"""
Base Noise:
    AV1_PRNG_RMS = 24.0  # Real average fluctuation of the AV1 generator

Luma Amplitude at pixel Y:
    f(Y) = linear_interp(sY_curve, Y)
    # The magic: AR_Gain and Norm_Factor cancel each other out, keeping f(Y) absolute
    Amplitude(Y) = (PV_Noise * AR_Gain * Norm_Factor * f(Y)) / 2^scaling_shift

Chroma Amplitude:
    combined = L x (luma_mult - 128) + chroma_mid x (mult - 128)
    index    = Clip3(0, 255, (combined >> 6) + (offset - 256))
    f_c      = interpolate_scaling(sCb_curve, index)
    Amplitude(C) = (PV_Noise * AR_Gain_C * Norm_Factor_C * f_c) / 2^scaling_shift
"""

from __future__ import annotations


AV1_PRNG_RMS = 24.0

P_FIELDS = [
    "ar_coeff_lag",  # 0: 0-3
    "ar_coeff_shift",  # 1: 6-9
    "grain_scale_shift",  # 2: 0-3
    "scaling_shift",  # 3: 8-11
    "chroma_scaling_from_luma",  # 4: 0/1
    "overlap_flag",  # 5: 0/1
    "cb_mult",  # 6
    "cb_luma_mult",  # 7
    "cb_offset",  # 8
    "cr_mult",  # 9
    "cr_luma_mult",  # 10
    "cr_offset",  # 11
]

P_DEFAULTS = {
    "ar_coeff_lag": 3,
    "ar_coeff_shift": 8,
    "grain_scale_shift": 0,
    "scaling_shift": 8,
    "chroma_scaling_from_luma": 0,
    "overlap_flag": 1,
    "cb_mult": 128,
    "cb_luma_mult": 128,
    "cb_offset": 256,
    "cr_mult": 128,
    "cr_luma_mult": 128,
    "cr_offset": 256,
}


def parse_p_row(tokens: list[str]) -> dict:
    result = dict(P_DEFAULTS)
    for i, field in enumerate(P_FIELDS):
        if i < len(tokens):
            try:
                result[field] = int(tokens[i])
            except ValueError:
                pass
    return result


def p_params_to_tokens(p: dict) -> list[str]:
    return [str(p.get(f, P_DEFAULTS[f])) for f in P_FIELDS]


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


def compute_ar_gain(cy_coeffs: list[int], ar_shift: int) -> float:
    if not cy_coeffs:
        return 1.0
    total = sum(cy_coeffs)
    denominator = 1.0 - total / (2**ar_shift)
    if abs(denominator) < 1e-9:
        return 1.0
    return 1.0 / denominator


def compute_ar_norm_factor(cy_coeffs: list[int], ar_shift: int) -> float:
    """
    Auto-Gain Control: returns the normalisation factor = 1 - sum(cY) / 2^ar_shift.
    Returns the RAW value — may be <= 0 if the AR filter is unstable.
    """
    if not cy_coeffs:
        return 1.0
    return 1.0 - sum(cy_coeffs) / (2**ar_shift)


def get_base_noise_energy(noise_setting_ui: float) -> float:
    """The raw physical energy produced by the AV1 PRNG (~24.0 RMS)."""
    return AV1_PRNG_RMS * (noise_setting_ui / 100.0)


def get_psychovisual_factor(grain_size: int) -> float:
    """
    The scaling factor that describes how much we REDUCE the amplitude
    so it looks 'natural' (or how much we want to balance it).
    Factor = (23 - grain_size) / 50.0
    """
    return (23 - grain_size) / 50.0


def psychovisual_noise_base(grain_size: int, noise_setting_ui: float) -> float:
    """
    Legacy helper: returns (Base * PsychovisualFactor).
    Used for the 'Balanced' target force.
    """
    return get_base_noise_energy(noise_setting_ui) * get_psychovisual_factor(grain_size)


def build_luma_amplitude_curve(
    xs: list[int],
    ys: list[int],
    grain_size: int,
    noise_setting: float,
    cy_coeffs: list[int],
    p_params: dict,
    luma_range: range = range(0, 256),
) -> tuple[list[int], list[float], list[float]]:
    """
    Returns the REAL amplitude in pixels, respecting the user's UI choices.
    """
    scaling_shift = p_params.get("scaling_shift", 8)
    scaling_divisor = 2**scaling_shift

    # Energy logic: ar_gain * norm_factor = 1.0 (if stable)
    # We always use the psychovisual noise as the base energy for the preview result
    total_noise_energy = psychovisual_noise_base(grain_size, noise_setting)

    luma_values: list[int] = list(luma_range)
    force_raw: list[float] = []
    amplitude_val: list[float] = []

    for y in luma_values:
        f_y = interpolate_scaling(xs, ys, y)
        force_raw.append(f_y)

        final_amplitude = (total_noise_energy * f_y) / scaling_divisor
        amplitude_val.append(final_amplitude)

    return luma_values, amplitude_val, force_raw


def _clip3(lo: int, hi: int, val: int) -> int:
    return max(lo, min(hi, val))


def build_chroma_amplitude_curve(
    sy_xs: list[int],
    sy_ys: list[int],
    cb_xs: list[int],
    cb_ys: list[int],
    cr_xs: list[int],
    cr_ys: list[int],
    grain_size: int,
    noise_setting: float,
    cb_coeffs: list[int],
    cr_coeffs: list[int],
    p_params: dict,
    luma_range: range = range(0, 256),
) -> dict[str, tuple[list[int], list[float], list[float]]]:
    """
    Returns the real fluctuation for Cb and Cr using spec-compliant index calculation.
    """
    scaling_shift = p_params.get("scaling_shift", 8)
    scaling_divisor = 2**scaling_shift

    chroma_mid = 128
    pv_noise = psychovisual_noise_base(grain_size, noise_setting)

    results: dict[str, tuple[list[int], list[float], list[float]]] = {}

    for ch, mult_key, luma_mult_key, offset_key, ch_xs, ch_ys, c_coeffs in [
        ("sCb", "cb_mult", "cb_luma_mult", "cb_offset", cb_xs, cb_ys, cb_coeffs),
        ("sCr", "cr_mult", "cr_luma_mult", "cr_offset", cr_xs, cr_ys, cr_coeffs),
    ]:
        mult = p_params.get(mult_key, 128)
        luma_mult = p_params.get(luma_mult_key, 128)
        offset = p_params.get(offset_key, 256)
        chroma_scaling_from_luma = p_params.get("chroma_scaling_from_luma", 0)

        total_chroma_energy = pv_noise

        luma_values: list[int] = list(luma_range)
        force_raw: list[float] = []
        amplitude_val: list[float] = []

        for L in luma_values:
            if chroma_scaling_from_luma:
                f_val = interpolate_scaling(sy_xs, sy_ys, L)
            else:
                combined = L * (luma_mult - 128) + chroma_mid * (mult - 128)
                index = _clip3(0, 255, (combined >> 6) + (offset - 256))
                f_val = interpolate_scaling(ch_xs, ch_ys, index)

            force_raw.append(f_val)

            final_amplitude = (total_chroma_energy * f_val) / scaling_divisor
            amplitude_val.append(final_amplitude)

        results[ch] = (luma_values, amplitude_val, force_raw)

    return results


_AUTOBALANCE_REF_SIZE = 1  # reference grain_size (pv_sf ≈ 0.44)


def compute_export_scale_factor(
    grain_size: int, cy_coeffs: list[int], ar_shift: int
) -> float:
    """
    scale = (Perceived_Target) / (Physical_Amplitude)
          = (PV_Factor(ref=1)) / (PV_Factor(size) * AR_Gain)
          = (PV_Factor(1) / PV_Factor(size)) * Norm_Factor
    """
    pv_ref = get_psychovisual_factor(_AUTOBALANCE_REF_SIZE)  # 0.44
    pv_cur = get_psychovisual_factor(grain_size)

    if abs(pv_cur) < 1e-9:
        pv_cur = 1.0

    norm_factor = compute_ar_norm_factor(cy_coeffs, ar_shift)
    if norm_factor <= 0.0:
        norm_factor = 1.0  # Safety fallback

    return (pv_ref / pv_cur) * norm_factor


def apply_autobalance_to_scale_data(
    scale_data: dict, grain_size: int, ar_coeffs_dict: dict, ar_shift: int
) -> dict:
    result: dict = {}
    for ch, data in scale_data.items():
        if ch == "sY":
            coeffs = ar_coeffs_dict.get("cY", [])
        elif ch == "sCb":
            coeffs = ar_coeffs_dict.get("cCb", [])
        else:
            coeffs = ar_coeffs_dict.get("cCr", [])

        scale = compute_export_scale_factor(grain_size, coeffs, ar_shift)

        xs = list(data.get("x", []))
        ys = [min(max(int(round(v * scale)), 0), 255) for v in data.get("y", [])]
        result[ch] = {"x": xs, "y": ys}

    return result


def _extract_coeffs(raw_lines: list[str], key: str) -> list[int]:
    for line in raw_lines:
        tokens = line.strip().split()
        if not tokens or tokens[0] != key:
            continue
        result: list[int] = []
        for t in tokens[1:]:
            try:
                result.append(int(t.rstrip(".,;")))
            except ValueError:
                pass
        return result
    return []


def extract_cy_from_raw_lines(raw_lines: list[str]) -> list[int]:
    return _extract_coeffs(raw_lines, "cY")


def extract_ar_coeffs_from_raw_lines(
    raw_lines: list[str],
) -> tuple[list[int], list[int], list[int]]:
    return (
        _extract_coeffs(raw_lines, "cY"),
        _extract_coeffs(raw_lines, "cCb"),
        _extract_coeffs(raw_lines, "cCr"),
    )


def validate_fgs_pipeline(
    coeffs: list[int],
    ar_shift: int,
    curve_points_y: list[int],
    autobalance_scale: float = 1.0,
) -> list[str]:

    warnings = []

    if len(curve_points_y) < 2:
        return warnings

    if coeffs:
        total_sum = sum(coeffs)
        max_allowed = 2**ar_shift

        if total_sum >= max_allowed:
            warnings.append(
                f"AR_MATH_ERROR: The algebraic sum of the coefficients ({total_sum}) "
                f"exceeds or equals the divisor ({max_allowed}). Calculated energy "
                "would be negative and the preview cannot be computed."
            )

    if curve_points_y:
        max_curve_val = max(curve_points_y)
        baked_max_curve = max_curve_val * autobalance_scale
        if baked_max_curve > 255:
            warnings.append(
                f"CURVE_CLIPPING: Export will push the curve up to {int(baked_max_curve)}. "
                "The maximum allowed is 255, so the curve shape will be clipped. "
                "Reduce the original curve or turn off Autobalance."
            )

    return warnings
