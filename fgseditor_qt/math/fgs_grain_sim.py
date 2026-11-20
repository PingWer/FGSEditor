from __future__ import annotations
import functools
import numpy as np

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


def _lfsr_next(state: int) -> tuple[int, int]:
    bit = ((state >> 0) ^ (state >> 1) ^ (state >> 3) ^ (state >> 12)) & 1
    new_state = ((state >> 1) | (bit << 15)) & 0xFFFF
    value = (new_state >> 5) & 0x7FF  # top 11 bits → 0..2047
    return new_state, value


def _build_ar_offsets(lag: int) -> list[tuple[int, int]]:
    """
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



@functools.lru_cache(maxsize=2048)
def _base_grain_2d(
    seed: int,
    width: int,
    height: int,
    grain_scale_shift: int,
) -> tuple[np.ndarray, int]:
    """Generate cached 2D base Gaussian noise field and final 16-bit LFSR state."""
    state = seed & 0xFFFF
    if state == 0:
        state = DEFAULT_SEED

    n = width * height
    arr = [0] * n
    gseq = GAUSSIAN_SEQUENCE

    if grain_scale_shift > 0:
        gs_round = 1 << (grain_scale_shift - 1)
        for i in range(n):
            bit = (state ^ (state >> 1) ^ (state >> 3) ^ (state >> 12)) & 1
            state = ((state >> 1) | (bit << 15)) & 0xFFFF
            arr[i] = (gseq[(state >> 5) & 0x7FF] + gs_round) >> grain_scale_shift
    else:
        for i in range(n):
            bit = (state ^ (state >> 1) ^ (state >> 3) ^ (state >> 12)) & 1
            state = ((state >> 1) | (bit << 15)) & 0xFFFF
            arr[i] = gseq[(state >> 5) & 0x7FF]

    arr_np = np.asarray(arr, dtype=np.int32).reshape(height, width)
    arr_np.setflags(write=False)
    return arr_np, state


def _generate_grain_2d(
    seed: int,
    width: int,
    height: int,
    ar_coeffs: list[int] | tuple[int, ...],
    ar_lag: int,
    ar_shift: int,
    grain_scale_shift: int = 0,
    luma_mult: int = 0,
    luma_2d: np.ndarray | None = None,
    sub_x: int = 1,
    sub_y: int = 1,
) -> tuple[int, int, int, np.ndarray]:
    """Generate a 2D grain noise array and its extrema using hybrid NumPy AR recurrence."""
    base_2d, final_state = _base_grain_2d(seed, width, height, grain_scale_shift)

    offsets = _build_ar_offsets(ar_lag)
    active_offsets = [
        (dy, dx, coeff)
        for (dy, dx), coeff in zip(offsets, ar_coeffs)
        if coeff != 0
    ]

    has_luma = luma_mult != 0 and luma_2d is not None
    if ar_shift <= 0 or (not active_offsets and not has_luma):
        region = np.clip(base_2d, GRAIN_MIN, GRAIN_MAX)
        return int(region.min()), int(region.max()), final_state, region

    ar_round = 1 << (ar_shift - 1)

    if not active_offsets:
        ar_sum = np.full((height, width), ar_round, dtype=np.int32)
        if has_luma:
            h_lim = min(height, (LUMA_GRAIN_HEIGHT + (1 << sub_y) - 1) >> sub_y)
            w_lim = min(width, (LUMA_GRAIN_WIDTH + (1 << sub_x) - 1) >> sub_x)
            ar_sum[:h_lim, :w_lim] += luma_mult * luma_2d[
                0 : (h_lim << sub_y) : (1 << sub_y),
                0 : (w_lim << sub_x) : (1 << sub_x),
            ]
        region = np.clip(
            base_2d + np.right_shift(ar_sum, ar_shift),
            GRAIN_MIN,
            GRAIN_MAX,
        )
        return int(region.min()), int(region.max()), final_state, region

    pad = max(3, ar_lag)
    tpl = np.zeros((height + pad, width + 2 * pad), dtype=np.int32)

    pre_const = np.full((height, width), ar_round, dtype=np.int32)
    if has_luma:
        h_lim = min(height, (LUMA_GRAIN_HEIGHT + (1 << sub_y) - 1) >> sub_y)
        w_lim = min(width, (LUMA_GRAIN_WIDTH + (1 << sub_x) - 1) >> sub_x)
        pre_const[:h_lim, :w_lim] += luma_mult * luma_2d[
            0 : (h_lim << sub_y) : (1 << sub_y),
            0 : (w_lim << sub_x) : (1 << sub_x),
        ]

    prev_terms = [(dy, dx, c) for dy, dx, c in active_offsets if dy < 0]
    same_terms = [(dx, c) for dy, dx, c in active_offsets if dy == 0]
    row_kernels_map: dict[int, np.ndarray] = {}
    if prev_terms:
        klen = 2 * ar_lag + 1
        for dy, dx, c in prev_terms:
            kern = row_kernels_map.get(dy)
            if kern is None:
                kern = np.zeros(klen, dtype=np.int32)
                row_kernels_map[dy] = kern
            kern[dx + ar_lag] = c
    kernels_list = list(row_kernels_map.items())
    s0 = pad - ar_lag
    s1 = pad + width + ar_lag
    row_acc = np.empty(width, dtype=np.int32)

    if not same_terms:
        for y in range(height):
            yp = y + pad
            np.copyto(row_acc, pre_const[y])
            for dy, kern in kernels_list:
                row_acc += np.correlate(tpl[yp + dy, s0:s1], kern, mode="valid")
            tpl[yp, pad : pad + width] = np.clip(
                base_2d[y] + np.right_shift(row_acc, ar_shift),
                GRAIN_MIN,
                GRAIN_MAX,
            )
    else:
        pre_lists = pre_const.tolist()
        base_lists = base_2d.tolist()
        use_fast_same = all(-3 <= dx < 0 for dx, _ in same_terms)
        coeff_map = dict(same_terms)
        cm3 = coeff_map.get(-3, 0)
        cm2 = coeff_map.get(-2, 0)
        cm1 = coeff_map.get(-1, 0)

        for y in range(height):
            yp = y + pad
            if kernels_list:
                np.copyto(row_acc, pre_const[y])
                for dy, kern in kernels_list:
                    row_acc += np.correlate(tpl[yp + dy, s0:s1], kern, mode="valid")
                acc_row = row_acc.tolist()
            else:
                acc_row = pre_lists[y]

            b_row = base_lists[y]
            row_buf = [0] * (width + pad)
            if use_fast_same:
                for x in range(width):
                    xp = x + pad
                    s = (
                        acc_row[x]
                        + cm3 * row_buf[xp - 3]
                        + cm2 * row_buf[xp - 2]
                        + cm1 * row_buf[xp - 1]
                    )
                    g = b_row[x] + (s >> ar_shift)
                    if g < GRAIN_MIN:
                        g = GRAIN_MIN
                    elif g > GRAIN_MAX:
                        g = GRAIN_MAX
                    row_buf[xp] = g
            else:
                for x in range(width):
                    xp = x + pad
                    s = acc_row[x]
                    for dx, c in same_terms:
                        s += c * row_buf[xp + dx]
                    g = b_row[x] + (s >> ar_shift)
                    if g < GRAIN_MIN:
                        g = GRAIN_MIN
                    elif g > GRAIN_MAX:
                        g = GRAIN_MAX
                    row_buf[xp] = g
            tpl[yp, pad : pad + width] = row_buf[pad:]

    region = tpl[pad:, pad : pad + width]
    return int(region.min()), int(region.max()), final_state, region


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
    luma_2d = None
    if luma_template is not None:
        luma_2d = np.asarray(luma_template, dtype=np.int32).reshape(
            LUMA_GRAIN_HEIGHT, LUMA_GRAIN_WIDTH
        )
    rmin, rmax, final_state, region = _generate_grain_2d(
        seed=seed,
        width=width,
        height=height,
        ar_coeffs=ar_coeffs,
        ar_lag=ar_lag,
        ar_shift=ar_shift,
        grain_scale_shift=grain_scale_shift,
        luma_mult=luma_mult,
        luma_2d=luma_2d,
        sub_x=sub_x,
        sub_y=sub_y,
    )
    return rmin, rmax, final_state, region.ravel().tolist()


@functools.lru_cache(maxsize=4096)
def get_luma_max_cached(
    cy_coeffs: tuple[int, ...],
    ar_lag: int,
    ar_shift: int,
    grain_scale_shift: int = 0,
) -> int:
    if not cy_coeffs or ar_lag == 0:
        return 1688

    offsets = _build_ar_offsets(ar_lag)
    has_offsets = len(offsets) > 0
    ar_round = (1 << (ar_shift - 1)) if ar_shift > 0 else 0
    state = DEFAULT_SEED
    real_max = -4096
    template = [0] * (LUMA_GRAIN_WIDTH * LUMA_GRAIN_HEIGHT)

    for y in range(LUMA_GRAIN_HEIGHT):
        y_offset = y * LUMA_GRAIN_WIDTH
        for x in range(LUMA_GRAIN_WIDTH):
            state, pos = _lfsr_next(state)
            base_grain = GAUSSIAN_SEQUENCE[pos] >> grain_scale_shift

            if has_offsets and ar_shift > 0:
                ar_sum = 0
                for idx, (dy, dx) in enumerate(offsets):
                    py = y + dy
                    px = x + dx
                    if 0 <= py < LUMA_GRAIN_HEIGHT and 0 <= px < LUMA_GRAIN_WIDTH:
                        coeff = cy_coeffs[idx]
                        if coeff != 0:
                            ar_sum += coeff * template[py * LUMA_GRAIN_WIDTH + px]
                grain = base_grain + ((ar_sum + ar_round) >> ar_shift)
            else:
                grain = base_grain

            if grain > GRAIN_MAX:
                grain = GRAIN_MAX
            elif grain < GRAIN_MIN:
                grain = GRAIN_MIN
            template[y_offset + x] = grain

            if grain > real_max:
                real_max = grain
                if real_max >= GRAIN_MAX:
                    return GRAIN_MAX

    return real_max


def _compute_grain_extremes_core(
    seed: int,
    cy_coeffs: tuple[int, ...],
    cb_coeffs: tuple[int, ...],
    cr_coeffs: tuple[int, ...],
    ar_lag: int,
    ar_shift: int,
    grain_scale_shift: int = 0,
    is_444: bool = False,
    needed_channels: tuple[str, ...] = ("sY", "sCb", "sCr"),
) -> dict[str, int]:
    expected_spatial_ar = len(_build_ar_offsets(ar_lag))
    chroma_w = CHROMA_GRAIN_WIDTH_444 if is_444 else CHROMA_GRAIN_WIDTH_420
    chroma_h = CHROMA_GRAIN_HEIGHT_444 if is_444 else CHROMA_GRAIN_HEIGHT_420
    sub_x = 0 if is_444 else 1
    sub_y = 0 if is_444 else 1

    need_cb = "sCb" in needed_channels
    need_cr = "sCr" in needed_channels

    cb_ar = cb_coeffs[:expected_spatial_ar] if cb_coeffs else ()
    cb_luma_mult = (
        cb_coeffs[expected_spatial_ar]
        if cb_coeffs and len(cb_coeffs) > expected_spatial_ar
        else 0
    )
    cr_ar = cr_coeffs[:expected_spatial_ar] if cr_coeffs else ()
    cr_luma_mult = (
        cr_coeffs[expected_spatial_ar]
        if cr_coeffs and len(cr_coeffs) > expected_spatial_ar
        else 0
    )

    need_luma = (
        "sY" in needed_channels
        or (need_cb and cb_luma_mult != 0)
        or (need_cr and cr_luma_mult != 0)
    )

    luma_min, luma_max, luma_2d = 0, 0, None
    if need_luma:
        luma_min, luma_max, _, luma_2d = _generate_grain_2d(
            seed=seed,
            width=LUMA_GRAIN_WIDTH,
            height=LUMA_GRAIN_HEIGHT,
            ar_coeffs=cy_coeffs,
            ar_lag=ar_lag,
            ar_shift=ar_shift,
            grain_scale_shift=grain_scale_shift,
        )

    cb_min, cb_max = 0, 0
    if need_cb:
        cb_seed = (seed ^ 0xB524) & 0xFFFF
        cb_min, cb_max, _, _ = _generate_grain_2d(
            seed=cb_seed,
            width=chroma_w,
            height=chroma_h,
            ar_coeffs=cb_ar,
            ar_lag=ar_lag,
            ar_shift=ar_shift,
            grain_scale_shift=grain_scale_shift,
            luma_mult=cb_luma_mult,
            luma_2d=luma_2d,
            sub_x=sub_x,
            sub_y=sub_y,
        )

    cr_min, cr_max = 0, 0
    if need_cr:
        cr_seed = (seed ^ 0x49D8) & 0xFFFF
        cr_min, cr_max, _, _ = _generate_grain_2d(
            seed=cr_seed,
            width=chroma_w,
            height=chroma_h,
            ar_coeffs=cr_ar,
            ar_lag=ar_lag,
            ar_shift=ar_shift,
            grain_scale_shift=grain_scale_shift,
            luma_mult=cr_luma_mult,
            luma_2d=luma_2d,
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
    return _compute_grain_extremes_core(
        seed=seed,
        cy_coeffs=cy_coeffs,
        cb_coeffs=cb_coeffs,
        cr_coeffs=cr_coeffs,
        ar_lag=ar_lag,
        ar_shift=ar_shift,
        grain_scale_shift=grain_scale_shift,
        is_444=is_444,
    )


def compute_grain_extremes(
    seed: int,
    cy_coeffs: list[int],
    cb_coeffs: list[int],
    cr_coeffs: list[int],
    ar_lag: int,
    ar_shift: int,
    grain_scale_shift: int = 0,
    is_444: bool = False,
    channels: tuple[str, ...] = ("sY", "sCb", "sCr"),
) -> dict[str, int]:
    cy_t = tuple(cy_coeffs) if cy_coeffs else ()
    cb_t = tuple(cb_coeffs) if cb_coeffs else ()
    cr_t = tuple(cr_coeffs) if cr_coeffs else ()
    if set(channels) >= {"sY", "sCb", "sCr"}:
        return compute_grain_extremes_cached(
            seed,
            cy_t,
            cb_t,
            cr_t,
            ar_lag,
            ar_shift,
            grain_scale_shift,
            is_444,
        )
    return _compute_grain_extremes_core(
        seed=seed,
        cy_coeffs=cy_t,
        cb_coeffs=cb_t,
        cr_coeffs=cr_t,
        ar_lag=ar_lag,
        ar_shift=ar_shift,
        grain_scale_shift=grain_scale_shift,
        is_444=is_444,
        needed_channels=channels,
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


def _channel_clip_thresholds(
    ch: str,
    bit_depth: int,
    is_full_range: bool,
) -> tuple[int, int, float, float]:
    step = 2.0 ** (-(bit_depth - 8))
    min_bound = 0 if is_full_range else 16
    max_bound = 255 if is_full_range else (240 if ch in ("sCb", "sCr") else 235)
    return min_bound, max_bound, min_bound - step, max_bound + step


def _channel_can_clip(
    xs: list[int],
    ys: list[int],
    ch: str,
    scaling_shift: int,
    bit_depth: int = 8,
    is_full_range: bool = False,
    fix_endpoints: bool = False,
) -> bool:
    """Return True if any eligible point could clip under worst-case grain [-2048, +2047]."""
    n_pts = len(xs)
    if len(ys) < n_pts:
        return False
    if fix_endpoints:
        if n_pts < 1:
            return False
        indices = range(0, n_pts)
    else:
        if n_pts < 3:
            return False
        indices = range(1, n_pts - 1)

    _, _, low_threshold, high_threshold = _channel_clip_thresholds(ch, bit_depth, is_full_range)
    for i in indices:
        if fix_endpoints and (i == 0 or i == n_pts - 1) and ys[i] <= 0:
            continue
        d_gmin = compute_amplitude_at_point(GRAIN_MIN, ys[i], scaling_shift)
        d_gmax = compute_amplitude_at_point(GRAIN_MAX, ys[i], scaling_shift)
        d_lo = d_gmin if d_gmin <= d_gmax else d_gmax
        d_hi = d_gmax if d_gmin <= d_gmax else d_gmin
        if (xs[i] + d_lo) <= low_threshold or (xs[i] + d_hi) >= high_threshold:
            return True
    return False


def fix_channel_clipping_points(
    xs: list[int],
    ys: list[int],
    ch: str,
    grain_min: int,
    grain_max: int,
    scaling_shift: int,
    bit_depth: int = 8,
    is_full_range: bool = False,
    fix_endpoints: bool = False,
) -> tuple[list[int], list[int], int]:
    """Fix clipping on a single scaling channel, returning ``(new_xs, new_ys, max_shift)``.

    - Interior points (``1 .. n-2``) are shifted horizontally.
    - When *fix_endpoints* is True:
      - On curves with 3+ points (or 1 point), clipping endpoints are set to strength 0.
      - On curves with exactly 2 points, safety-ramp points at strength 0 are inserted at
        the range borders and the clipping endpoint(s) are moved inward to preserve grain.
    """
    import math

    n_pts = len(xs)
    if n_pts == 0 or len(ys) < n_pts:
        return list(xs), list(ys), 0
    if not fix_endpoints and n_pts < 3:
        return list(xs), list(ys), 0

    min_bound, max_bound, low_threshold, high_threshold = _channel_clip_thresholds(
        ch, bit_depth, is_full_range
    )

    def _point_clips(px: int, py: int) -> bool:
        d_min = compute_amplitude_at_point(grain_min, py, scaling_shift)
        d_max = compute_amplitude_at_point(grain_max, py, scaling_shift)
        return (px + d_min) <= low_threshold or (px + d_max) >= high_threshold

    def _max_safe_y(px: int, cur_y: int) -> int:
        if cur_y <= 0:
            return 0
        if not _point_clips(px, cur_y):
            return cur_y
        lo, hi = 0, cur_y
        best = 0
        while lo <= hi:
            mid = (lo + hi) // 2
            if not _point_clips(px, mid):
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    if fix_endpoints and n_pts == 1:
        new_ys = list(ys)
        if ys[0] > 0 and _point_clips(xs[0], ys[0]):
            new_ys[0] = 0
        return list(xs), new_ys, 0

    if fix_endpoints and n_pts == 2:
        d_min_0 = compute_amplitude_at_point(grain_min, ys[0], scaling_shift)
        d_max_0 = compute_amplitude_at_point(grain_max, ys[0], scaling_shift)
        d_min_1 = compute_amplitude_at_point(grain_min, ys[1], scaling_shift)
        d_max_1 = compute_amplitude_at_point(grain_max, ys[1], scaling_shift)

        left_clips = ys[0] > 0 and (
            (xs[0] + d_min_0) <= low_threshold or (xs[0] + d_max_0) >= high_threshold
        )
        right_clips = ys[1] > 0 and (
            (xs[1] + d_min_1) <= low_threshold or (xs[1] + d_max_1) >= high_threshold
        )
        if not left_clips and not right_clips:
            return list(xs), list(ys), 0

        anchor_x0 = min_bound
        anchor_x1 = max_bound

        target_x0 = xs[0]
        if left_clips:
            if (xs[0] + d_min_0) <= low_threshold:
                target_x0 = max(anchor_x0 + 1, int(math.ceil(low_threshold - d_min_0 + 0.001)))
            else:
                target_x0 = min(anchor_x1 - 1, int(math.floor(high_threshold - d_max_0 - 0.001)))

        target_x1 = xs[1]
        if right_clips:
            if (xs[1] + d_max_1) >= high_threshold:
                target_x1 = min(anchor_x1 - 1, int(math.floor(high_threshold - d_max_1 - 0.001)))
            else:
                target_x1 = max(anchor_x0 + 1, int(math.ceil(low_threshold - d_min_1 + 0.001)))

        if left_clips and right_clips:
            target_x0 = max(anchor_x0 + 1, min(anchor_x1 - 2, target_x0))
            target_x1 = max(anchor_x0 + 2, min(anchor_x1 - 1, target_x1))
            if target_x0 >= target_x1:
                mid = (anchor_x0 + anchor_x1) // 2
                target_x0 = max(anchor_x0 + 1, min(anchor_x1 - 2, mid))
                target_x1 = target_x0 + 1
            safe_y0 = _max_safe_y(target_x0, ys[0])
            safe_y1 = _max_safe_y(target_x1, ys[1])
            new_xs = [anchor_x0, target_x0, target_x1, anchor_x1]
            new_ys = [0, safe_y0, safe_y1, 0]
            max_shift = max(abs(target_x0 - xs[0]), abs(target_x1 - xs[1]))
            return new_xs, new_ys, max_shift

        if left_clips:
            if xs[1] <= anchor_x0 + 1:
                return list(xs), [0, ys[1]], 0
            target_x0 = max(anchor_x0 + 1, min(xs[1] - 1, target_x0))
            safe_y0 = _max_safe_y(target_x0, ys[0])
            return [anchor_x0, target_x0, xs[1]], [0, safe_y0, ys[1]], abs(target_x0 - xs[0])

        # right_clips only
        if xs[0] >= anchor_x1 - 1:
            return list(xs), [ys[0], 0], 0
        target_x1 = min(anchor_x1 - 1, max(xs[0] + 1, target_x1))
        safe_y1 = _max_safe_y(target_x1, ys[1])
        return [xs[0], target_x1, anchor_x1], [ys[0], safe_y1, 0], abs(target_x1 - xs[1])

    new_ys = list(ys)
    if fix_endpoints:
        if ys[0] > 0 and _point_clips(xs[0], ys[0]):
            new_ys[0] = 0
        if ys[-1] > 0 and _point_clips(xs[-1], ys[-1]):
            new_ys[-1] = 0

    shifts: dict[int, tuple[str, int]] = {}
    for i in range(1, n_pts - 1):
        d_min = compute_amplitude_at_point(grain_min, ys[i], scaling_shift)
        d_max = compute_amplitude_at_point(grain_max, ys[i], scaling_shift)

        min_valid = max(min_bound + i, xs[0] + i)
        max_valid = min(max_bound - (n_pts - 1 - i), xs[-1] - (n_pts - 1 - i))

        if (xs[i] + d_min) <= low_threshold:
            target_x = int(math.ceil(low_threshold - d_min + 0.001))
            target_x = max(min_valid, min(max_valid, target_x))
            shifts[i] = ("bottom", target_x)
        elif (xs[i] + d_max) >= high_threshold:
            target_x = int(math.floor(high_threshold - d_max - 0.001))
            target_x = max(min_valid, min(max_valid, target_x))
            shifts[i] = ("top", target_x)

    if not shifts:
        return list(xs), new_ys, 0

    new_xs = list(xs)

    for i in range(1, n_pts - 1):
        if i in shifts and shifts[i][0] == "bottom":
            target_x = shifts[i][1]
            if new_xs[i] < target_x:
                new_xs[i] = target_x
        new_xs[i] = max(new_xs[i], new_xs[i - 1] + 1)
        if new_xs[i] >= new_xs[i + 1]:
            for j in range(i + 1, n_pts - 1):
                if new_xs[j] <= new_xs[j - 1]:
                    new_xs[j] = new_xs[j - 1] + 1
                else:
                    break

    for i in range(n_pts - 2, 0, -1):
        if i in shifts and shifts[i][0] == "top":
            target_x = shifts[i][1]
            if new_xs[i] > target_x:
                new_xs[i] = target_x
        new_xs[i] = min(new_xs[i], new_xs[i + 1] - 1)
        if new_xs[i] <= new_xs[i - 1]:
            for j in range(i - 1, 0, -1):
                if new_xs[j] >= new_xs[j + 1]:
                    new_xs[j] = new_xs[j + 1] - 1
                else:
                    break

    for i in range(n_pts - 2, 0, -1):
        if new_xs[i] >= new_xs[i + 1]:
            new_xs[i] = new_xs[i + 1] - 1

    for i in range(1, n_pts - 1):
        if new_xs[i] <= new_xs[i - 1]:
            new_xs[i] = new_xs[i - 1] + 1

    max_shift = max(abs(new_xs[i] - xs[i]) for i in range(n_pts))
    return new_xs, new_ys, max_shift


def fix_channel_clipping(
    xs: list[int],
    ys: list[int],
    ch: str,
    grain_min: int,
    grain_max: int,
    scaling_shift: int,
    bit_depth: int = 8,
    is_full_range: bool = False,
) -> tuple[list[int], int]:
    new_xs, _, max_shift = fix_channel_clipping_points(
        xs,
        ys,
        ch,
        grain_min=grain_min,
        grain_max=grain_max,
        scaling_shift=scaling_shift,
        bit_depth=bit_depth,
        is_full_range=is_full_range,
        fix_endpoints=False,
    )
    return new_xs, max_shift


def is_event_full_range(event: dict, video_info: dict | None = None) -> bool:
    if video_info and str(video_info.get("color_range") or "").strip().lower() in ("pc", "full"):
        return True
    from fgseditor_qt.core import fgs_parser
    sd = event.get("scale_data") or fgs_parser.get_scale_data(event)
    if sd:
        for ch in ("sY", "sCb", "sCr"):
            xs = sd.get(ch, {}).get("x", [])
            max_limit = 240 if ch in ("sCb", "sCr") else 235
            if any(x < 16 or x > max_limit for x in xs):
                return True
    return False


def event_potentially_clipping_channels(
    event: dict,
    bit_depth: int = 8,
    is_full_range: bool | None = None,
    channels: tuple[str, ...] = ("sY", "sCb", "sCr"),
    video_info: dict | None = None,
    fix_endpoints: bool = False,
) -> tuple[str, ...]:
    """Return active channels of *event* that could clip under worst-case grain bounds."""
    from fgseditor_qt.core import fgs_parser

    if fgs_parser.get_apply_grain(event) == 0 or fgs_parser.get_update_parameters(event) == 0:
        return ()

    p_params = fgs_parser.get_p_params(event)
    scaling_shift = fgs_parser.get_scaling_shift(event)
    chroma_from_luma = p_params.get("chroma_scaling_from_luma", 0) == 1
    scale_data = event.get("scale_data") or fgs_parser.get_scale_data(event)
    if not scale_data:
        return ()

    if is_full_range is None:
        is_full_range = is_event_full_range(event, video_info)

    candidates: list[str] = []
    for ch in channels:
        if ch not in scale_data:
            continue
        if chroma_from_luma and ch in ("sCb", "sCr"):
            continue
        ch_data = scale_data[ch]
        if _channel_can_clip(
            ch_data.get("x", []),
            ch_data.get("y", []),
            ch,
            scaling_shift,
            bit_depth=bit_depth,
            is_full_range=is_full_range,
            fix_endpoints=fix_endpoints,
        ):
            candidates.append(ch)
    return tuple(candidates)


def fix_event_clipping(
    event: dict,
    bit_depth: int = 8,
    is_full_range: bool = False,
    channels: tuple[str, ...] = ("sY", "sCb", "sCr"),
    is_444: bool = False,
    extremes: dict[str, int] | None = None,
    fix_endpoints: bool = False,
) -> tuple[bool, int]:
    """Check and shift scaling points to fix AR grain clipping.

    When *extremes* is already precomputed (e.g. via a background batch pool),
    pass it to skip recomputing the 64x64 Monte-Carlo grain block.
    """
    import copy
    from fgseditor_qt.core import fgs_parser
    from fgseditor_qt.core.fgs_save import _build_scale_line

    needed_channels = event_potentially_clipping_channels(
        event,
        bit_depth=bit_depth,
        is_full_range=is_full_range,
        channels=channels,
        fix_endpoints=fix_endpoints,
    )
    if not needed_channels:
        return False, 0

    p_params = fgs_parser.get_p_params(event)
    scaling_shift = fgs_parser.get_scaling_shift(event)
    lag = p_params.get("ar_coeff_lag", 3)
    ar_shift = p_params.get("ar_coeff_shift", 6)
    grain_scale_shift = p_params.get("grain_scale_shift", 0)
    seed = fgs_parser.get_grain_seed(event)

    if extremes is None:
        cy, cb, cr = fgs_parser.extract_ar_coeffs_from_raw_lines(event.get("raw_lines", []))
        extremes = compute_grain_extremes(
            seed=seed,
            cy_coeffs=cy,
            cb_coeffs=cb,
            cr_coeffs=cr,
            ar_lag=lag,
            ar_shift=ar_shift,
            grain_scale_shift=grain_scale_shift,
            is_444=is_444,
            channels=needed_channels,
        )

    scale_data = copy.deepcopy(event.get("scale_data") or fgs_parser.get_scale_data(event))
    overall_changed = False
    overall_max_shift = 0

    channel_map = {
        "sY": ("luma_min", "luma_max"),
        "sCb": ("cb_min", "cb_max"),
        "sCr": ("cr_min", "cr_max"),
    }

    chroma_from_luma = p_params.get("chroma_scaling_from_luma", 0) == 1

    for ch in needed_channels:
        xs = scale_data[ch].get("x", [])
        ys = scale_data[ch].get("y", [])

        min_k, max_k = channel_map[ch]
        new_xs, new_ys, shift = fix_channel_clipping_points(
            xs,
            ys,
            ch,
            grain_min=extremes.get(min_k, 0),
            grain_max=extremes.get(max_k, 0),
            scaling_shift=scaling_shift,
            bit_depth=bit_depth,
            is_full_range=is_full_range,
            fix_endpoints=fix_endpoints,
        )
        if new_xs != xs or new_ys != ys:
            scale_data[ch]["x"] = new_xs
            scale_data[ch]["y"] = new_ys
            overall_changed = True
            if shift > overall_max_shift:
                overall_max_shift = shift

    if overall_changed:
        event["scale_data"] = scale_data
        if "raw_lines" in event:
            new_raw = []
            for line in event["raw_lines"]:
                stripped = line.strip()
                parts = stripped.split()
                matched_ch = None
                if parts:
                    for ch in ("sY", "sCb", "sCr"):
                        if parts[0].lower() == ch.lower():
                            matched_ch = ch
                            break
                if matched_ch and matched_ch in scale_data:
                    built_line = _build_scale_line(
                        matched_ch,
                        scale_data[matched_ch],
                        chroma_from_luma=chroma_from_luma,
                    )
                    indent = line[: len(line) - len(line.lstrip())]
                    new_raw.append(indent + built_line.lstrip())
                else:
                    new_raw.append(line)
            event["raw_lines"] = new_raw

    return overall_changed, overall_max_shift

