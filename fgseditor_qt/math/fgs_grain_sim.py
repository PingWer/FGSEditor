from __future__ import annotations
import functools

from fgseditor_qt.core.AFGS_TABLE_and_SEEDS import GAUSSIAN_SEQUENCE

LUMA_GRAIN_WIDTH = 82
LUMA_GRAIN_HEIGHT = 73
CHROMA_GRAIN_WIDTH_420 = 44  # LUMA_GRAIN_WIDTH >> 1 + 3 padding
CHROMA_GRAIN_HEIGHT_420 = 38  # LUMA_GRAIN_HEIGHT >> 1 + 2 padding
CHROMA_GRAIN_WIDTH_444 = 82  # Full resolution 4:4:4 master content
CHROMA_GRAIN_HEIGHT_444 = 73

# Grain value range (12-bit signed)
GRAIN_MIN = -2048
GRAIN_MAX = 2047

DEFAULT_SEED = 7391


# LFSR — Linear Feedback Shift Register (spec-compliant)
def _lfsr_next(state: int) -> tuple[int, int]:
    """
    Advance the 16-bit LFSR by one step.

    Returns:
        (new_state, value_11bit)
        value_11bit: the top 11 bits of the NEW register,
                     i.e. (new_state >> 5) & 0x7FF
    """
    bit = ((state >> 0) ^ (state >> 1) ^ (state >> 3) ^ (state >> 12)) & 1
    new_state = ((state >> 1) | (bit << 15)) & 0xFFFF
    value = (new_state >> 5) & 0x7FF  # top 11 bits → 0..2047
    return new_state, value


def _build_ar_offsets(lag: int) -> list[tuple[int, int]]:
    """
    Build the ordered list of (deltaRow, deltaCol) offsets for the
    autoregressive filter, matching the AV1 spec coefficient ordering.

    Total coefficients per lag:
      lag 0 → 0,  lag 1 → 4,  lag 2 → 12,  lag 3 → 24
    """
    offsets: list[tuple[int, int]] = []
    for dy in range(-lag, 1):
        for dx in range(-lag, lag + 1):
            if dy == 0 and dx >= 0:
                break
            offsets.append((dy, dx))
    return offsets



def generate_grain_template(
    seed: int,
    width: int,
    height: int,
    ar_coeffs: list[int],
    ar_lag: int,
    ar_shift: int,
    grain_scale_shift: int = 0,
    luma_mult: int = 0,
    luma_template: list[int] | None = None,
    sub_x: int = 1,
    sub_y: int = 1,
) -> tuple[int, int, int, list[int]]:
    """
    Generate the full grain noise template and find its real extremes.

    Args:
        seed:              16-bit LFSR seed (must be non-zero).
        width:             Template width  (82 for luma, 44 for chroma 420).
        height:            Template height (73 for luma, 38 for chroma 420).
        ar_coeffs:         Spatial AR filter coefficients (may be empty if lag==0).
        ar_lag:            AR coefficient lag (0-3).
        ar_shift:          AR coefficient shift (typically 6-9).
        grain_scale_shift: Pre-scale of Gaussian noise (0-3). Higher = less noise.
        luma_mult:         Multiplier for chroma correlation with luma.
        luma_template:     The fully generated Luma grain template (flat list) to correlate with.
        sub_x:             Subsampling horizontal factor (1 for 4:2:0).
        sub_y:             Subsampling vertical factor (1 for 4:2:0).

    Returns:
        (real_min, real_max, final_state, generated_template)
    """
    state = seed & 0xFFFF
    if state == 0:
        state = DEFAULT_SEED

    # Rounding offset for the AR filter division
    ar_round = (1 << (ar_shift - 1)) if ar_shift > 0 else 0

    # Rounding offset for grain_scale_shift (Round2 from spec)
    gs_round = (1 << (grain_scale_shift - 1)) if grain_scale_shift > 0 else 0

    # Build the AR offset table and pre-filter active non-zero coefficients
    offsets = _build_ar_offsets(ar_lag)
    active_offsets = [
        (dy, dx, coeff)
        for (dy, dx), coeff in zip(offsets, ar_coeffs)
        if coeff != 0
    ]
    has_offsets = bool(active_offsets)

    template = [0] * (width * height)

    real_min = GRAIN_MAX
    real_max = GRAIN_MIN

    for y in range(height):
        y_offset = y * width
        for x in range(width):
            state, val = _lfsr_next(state)

            base_grain = GAUSSIAN_SEQUENCE[val]
            if grain_scale_shift > 0:
                base_grain = (base_grain + gs_round) >> grain_scale_shift

            ar_sum = 0
            if has_offsets:
                for dy, dx, coeff in active_offsets:
                    ref_y = y + dy
                    ref_x = x + dx
                    if 0 <= ref_y < height and 0 <= ref_x < width:
                        ar_sum += coeff * template[ref_y * width + ref_x]

            if luma_mult != 0 and luma_template is not None:
                luma_y = y << sub_y
                luma_x = x << sub_x
                if luma_y < LUMA_GRAIN_HEIGHT and luma_x < LUMA_GRAIN_WIDTH:
                    ar_sum += luma_mult * luma_template[luma_y * LUMA_GRAIN_WIDTH + luma_x]

            if ar_shift > 0 and (has_offsets or luma_mult != 0):
                grain = base_grain + ((ar_sum + ar_round) >> ar_shift)
            else:
                grain = base_grain

            if grain < GRAIN_MIN:
                grain = GRAIN_MIN
            elif grain > GRAIN_MAX:
                grain = GRAIN_MAX
            template[y_offset + x] = grain

            if grain < real_min:
                real_min = grain
            if grain > real_max:
                real_max = grain

    return real_min, real_max, state, template


@functools.lru_cache(maxsize=1024)
def compute_grain_extremes_cached(
    seed: int,
    cy_coeffs: tuple[int, ...],
    cb_coeffs: tuple[int, ...],
    cr_coeffs: tuple[int, ...],
    ar_lag: int,
    ar_shift: int,
    grain_scale_shift: int = 0,
    is_444: bool = False,
) -> dict[str, int]:
    expected_spatial_ar = len(_build_ar_offsets(ar_lag))


    luma_min, luma_max, state_after_luma, luma_template = generate_grain_template(
        seed=seed,
        width=LUMA_GRAIN_WIDTH,
        height=LUMA_GRAIN_HEIGHT,
        ar_coeffs=list(cy_coeffs),
        ar_lag=ar_lag,
        ar_shift=ar_shift,
        grain_scale_shift=grain_scale_shift,
    )

    chroma_w = CHROMA_GRAIN_WIDTH_444 if is_444 else CHROMA_GRAIN_WIDTH_420
    chroma_h = CHROMA_GRAIN_HEIGHT_444 if is_444 else CHROMA_GRAIN_HEIGHT_420
    sub_x = 0 if is_444 else 1
    sub_y = 0 if is_444 else 1

    cb_ar = list(cb_coeffs[:expected_spatial_ar]) if cb_coeffs else []
    cb_luma_mult = (
        cb_coeffs[expected_spatial_ar]
        if cb_coeffs and len(cb_coeffs) > expected_spatial_ar
        else 0
    )

    cb_seed = (seed ^ 0xB524) & 0xFFFF
    cb_min, cb_max, _, _ = generate_grain_template(
        seed=cb_seed,
        width=chroma_w,
        height=chroma_h,
        ar_coeffs=cb_ar,
        ar_lag=ar_lag,
        ar_shift=ar_shift,
        grain_scale_shift=grain_scale_shift,
        luma_mult=cb_luma_mult,
        luma_template=luma_template,
        sub_x=sub_x,
        sub_y=sub_y,
    )

    cr_ar = list(cr_coeffs[:expected_spatial_ar]) if cr_coeffs else []
    cr_luma_mult = (
        cr_coeffs[expected_spatial_ar]
        if cr_coeffs and len(cr_coeffs) > expected_spatial_ar
        else 0
    )

    cr_seed = (seed ^ 0x49D8) & 0xFFFF
    cr_min, cr_max, _, _ = generate_grain_template(
        seed=cr_seed,
        width=chroma_w,
        height=chroma_h,
        ar_coeffs=cr_ar,
        ar_lag=ar_lag,
        ar_shift=ar_shift,
        grain_scale_shift=grain_scale_shift,
        luma_mult=cr_luma_mult,
        luma_template=luma_template,
        sub_x=sub_x,
        sub_y=sub_y,
    )

    return {
        "luma_min": luma_min,
        "luma_max": luma_max,
        "cb_min": cb_min,
        "cb_max": cb_max,
        "cr_min": cr_min,
        "cr_max": cr_max,
    }


def compute_grain_extremes(
    seed: int,
    cy_coeffs: list[int],
    cb_coeffs: list[int],
    cr_coeffs: list[int],
    ar_lag: int,
    ar_shift: int,
    grain_scale_shift: int = 0,
    is_444: bool = False,
) -> dict[str, int]:
    """
    Generate Luma, Cb, Cr grain templates in sequence (sharing PRNG state)
    and return the real min/max for each plane. Uses LRU cache for high performance.
    """
    return compute_grain_extremes_cached(
        seed,
        tuple(cy_coeffs) if cy_coeffs else (),
        tuple(cb_coeffs) if cb_coeffs else (),
        tuple(cr_coeffs) if cr_coeffs else (),
        ar_lag,
        ar_shift,
        grain_scale_shift,
        is_444,
    )





def compute_amplitude_at_point(
    grain_extreme: int,
    scaling_value: float,
    scaling_shift: int,
) -> float:
    """
    Compute the grain delta at a specific curve point (UI/plotter use, float).

    NOTE: This uses float interpolation and is suitable for the timeline plotter.
    For bit-exact 10-bit synthesis use compute_amplitude_at_pixel_10bit().

    Mathematical breakdown:
    1. The grain template (grain_extreme) is in 12-bit signed domain (+-2048).
    2. Per AV1 spec, for 10-bit synthesis, the shift is (scaling_shift + (12 - 10)).
    3. We then scale from 10-bit world to 8-bit UI world (divide by 4).

    Total divisor = 2^(scaling_shift + 2 + 2) = 2^(scaling_shift + 4).
    """
    total_shift = scaling_shift + 4
    delta_8bit = (grain_extreme * scaling_value) / (1 << total_shift)
    return delta_8bit


def compute_amplitude_at_pixel_10bit(
    grain_value: int,
    scaling_lut: list[int],
    pixel_10bit: int,
    scaling_shift: int,
) -> int:
    """
    Compute the exact integer grain delta for a specific 10-bit pixel.
    Spec-compliant (AFGS1 section 8.2.5).

    Args:
        grain_value:   Raw grain template value (12-bit signed, range +-2048).
        scaling_lut:   Pre-built 256-entry LUT from build_scaling_lut().
        pixel_10bit:   The original pixel value in 10-bit (0-1023).
        scaling_shift: grain_scaling_minus8 + 8 (the ScalingShift from the spec).

    Returns:
        Integer noise delta to add to the original pixel, in 10-bit units.
    """
    from fgseditor_qt.math.fgs_math import scale_lut_10bit

    scaling_factor = scale_lut_10bit(scaling_lut, pixel_10bit)
    product = grain_value * scaling_factor
    # Round2(value, n) = (value + (1 << (n-1))) >> n
    noise = (product + (1 << (scaling_shift - 1))) >> scaling_shift
    return noise
