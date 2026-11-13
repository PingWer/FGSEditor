# ==============================================================================
# Copyright (c) 2019 Intel Corporation
# Copyright (c) 2026 Michele 'PingWer' Cosentino
#
# This source code is subject to the terms of the BSD 2 Clause License and
# the Alliance for Open Media Patent License 1.0. If the BSD 2 Clause License
# was not distributed with this source code in the LICENSE file, you can
# obtain it at https://www.aomedia.org/license/software-license. If the Alliance for Open
# Media Patent License 1.0 was not distributed with this source code in the
# PATENTS file, you can obtain it at https://www.aomedia.org/license/patent-license.
#
# Original SVT-AV1 C implementation by Intel Corporation.
# Python port, extended radiometric model, and custom solvers by Michele 'PingWer' Cosentino.
# ==============================================================================


import math
import argparse
import sys

# PQ Constants (SMPTE 2084)
PQ_M1 = 2610.0 / 16384
PQ_M2 = 128 * 2523.0 / 4096
PQ_C1 = 3424.0 / 4096
PQ_C2 = 32 * 2413.0 / 4096
PQ_C3 = 32 * 2392.0 / 4096

# HLG Constants
HLG_A = 0.17883277
HLG_B = 0.28466892
HLG_C = 0.55991073

# BT.601 / BT.709 / BT.2020 C1-Continuous Constants
BT709_ALPHA = 1.09929682680944
BT709_BETA = 0.018053968510807
BT709_THRESH = 4.5 * BT709_BETA  # 0.0812428582986315

# SMPTE 240M C1-Continuous Constants
SMPTE240_ALPHA = 1.111572195921731
SMPTE240_BETA = 0.022821585529445
SMPTE240_THRESH = 4.0 * SMPTE240_BETA  # 0.09128634211778


# Color Space <-> Linear Conversions
def gamma22_to_linear(g):
    return max(0.0, g) ** 2.2


def gamma22_from_linear(l):  # noqa: E741
    return max(0.0, l) ** (1.0 / 2.2)


def gamma28_to_linear(g):
    return max(0.0, g) ** 2.8


def gamma28_from_linear(l):  # noqa: E741
    return max(0.0, l) ** (1.0 / 2.8)


def gamma24_to_linear(g):
    return max(0.0, g) ** 2.4


def gamma24_from_linear(l):  # noqa: E741
    return max(0.0, l) ** (1.0 / 2.4)


def srgb_to_linear(srgb):
    srgb = max(0.0, srgb)
    return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4


def srgb_from_linear(linear):
    linear = max(0.0, linear)
    return (
        12.92 * linear
        if linear <= 0.0031308
        else 1.055 * (linear ** (1.0 / 2.4)) - 0.055
    )


def pq_to_linear(pq):
    pq = max(0.0, pq)
    pq_pow_inv_m2 = pq ** (1.0 / PQ_M2)
    num = max(0.0, pq_pow_inv_m2 - PQ_C1)
    den = PQ_C2 - PQ_C3 * pq_pow_inv_m2
    return (num / den) ** (1.0 / PQ_M1)


def pq_from_linear(linear):
    linear = max(0.0, linear)
    linear_pow_m1 = linear**PQ_M1
    return ((PQ_C1 + PQ_C2 * linear_pow_m1) / (1.0 + PQ_C3 * linear_pow_m1)) ** PQ_M2


def hlg_to_linear(hlg):
    hlg = max(0.0, hlg)
    linear = (
        hlg * hlg / 3.0
        if hlg <= 0.5
        else (math.exp((hlg - HLG_C) / HLG_A) + HLG_B) / 12.0
    )
    return linear**1.2


def hlg_from_linear(linear):
    linear = max(0.0, linear) ** (1.0 / 1.2)
    return (
        math.sqrt(3.0 * linear)
        if linear <= 1.0 / 12.0
        else HLG_A * math.log(12.0 * linear - HLG_B) + HLG_C
    )


def bt601_to_linear(E):
    E = max(0.0, E)
    return (
        E / 4.5
        if E < BT709_THRESH
        else ((E + (BT709_ALPHA - 1.0)) / BT709_ALPHA) ** (1.0 / 0.45)
    )


def bt601_from_linear(L):
    L = max(0.0, L)
    return (
        4.5 * L
        if L < BT709_BETA
        else BT709_ALPHA * (L**0.45) - (BT709_ALPHA - 1.0)
    )


def smpte240m_to_linear(x):
    x = max(0.0, x)
    return (
        x / 4.0
        if x < SMPTE240_THRESH
        else ((x + (SMPTE240_ALPHA - 1.0)) / SMPTE240_ALPHA) ** (1.0 / 0.45)
    )


def smpte240m_from_linear(y):
    y = max(0.0, y)
    return (
        4.0 * y
        if y < SMPTE240_BETA
        else SMPTE240_ALPHA * (y**0.45) - (SMPTE240_ALPHA - 1.0)
    )


def identity_to_linear(x):
    return x


def identity_from_linear(x):
    return x


def log100_to_linear(x):
    x = max(0.0, x)
    return ((10.0 ** (x * math.log10(101.0))) - 1.0) / 100.0


def log100_from_linear(y):
    y = max(0.0, y)
    return math.log10(100.0 * y + 1.0) / math.log10(101.0)


def log100_sqrt10_to_linear(x):
    x = max(0.0, x)
    scale = 100.0 * 3.1622776601683795
    return ((10.0 ** (x * math.log10(scale + 1.0))) - 1.0) / scale


def log100_sqrt10_from_linear(y):
    y = max(0.0, y)
    scale = 100.0 * 3.1622776601683795
    return math.log10(scale * y + 1.0) / math.log10(scale + 1.0)


def iec61966_to_linear(x):
    return bt601_to_linear(x)


def iec61966_from_linear(y):
    return bt601_from_linear(y)


def bt1361_to_linear(x):
    return bt601_to_linear(x)


def bt1361_from_linear(y):
    return bt601_from_linear(y)


def smpte428_to_linear(x):  # gamma 2.6
    return (52.37 / 48.0) * max(x, 0.0) ** 2.6


def smpte428_from_linear(y):
    return (48.0 / 52.37 * max(y, 0.0)) ** (1.0 / 2.6)


class TransferFunction:
    def __init__(self, to_linear_fn, from_linear_fn, mid_tone):
        self.to_linear = to_linear_fn
        self.from_linear = from_linear_fn
        self.mid_tone = mid_tone


# CICP Mapping Dictionary

TFS = {
    "BT_601": TransferFunction(bt601_to_linear, bt601_from_linear, 0.18),
    "SRGB": TransferFunction(srgb_to_linear, srgb_from_linear, 0.18),
    "GAMMA22": TransferFunction(gamma22_to_linear, gamma22_from_linear, 0.18),
    "GAMMA28": TransferFunction(gamma28_to_linear, gamma28_from_linear, 0.18),
    "GAMMA24": TransferFunction(gamma24_to_linear, gamma24_from_linear, 0.18),
    "SMPTE_240": TransferFunction(smpte240m_to_linear, smpte240m_from_linear, 0.18),
    "LINEAR": TransferFunction(identity_to_linear, identity_from_linear, 0.50),
    "LOG_100": TransferFunction(log100_to_linear, log100_from_linear, 0.18),
    "LOG_100_SQRT10": TransferFunction(
        log100_sqrt10_to_linear, log100_sqrt10_from_linear, 0.18
    ),
    "IEC_61966": TransferFunction(iec61966_to_linear, iec61966_from_linear, 0.18),
    "BT_1361": TransferFunction(bt1361_to_linear, bt1361_from_linear, 0.18),
    "SMPTE_428": TransferFunction(smpte428_to_linear, smpte428_from_linear, 0.18),
    "SMPTE_2084": TransferFunction(pq_to_linear, pq_from_linear, 26.0 / 10000.0),  # PQ
    "HLG": TransferFunction(hlg_to_linear, hlg_from_linear, 26.0 / 1000.0),
    # Standard aliases
    "BT_709": TransferFunction(bt601_to_linear, bt601_from_linear, 0.18),
    "BT_1886": TransferFunction(gamma24_to_linear, gamma24_from_linear, 0.18),
    "BT_2020_10_BIT (SDR)": TransferFunction(bt601_to_linear, bt601_from_linear, 0.18),
    "BT_2020_12_BIT (SDR)": TransferFunction(bt601_to_linear, bt601_from_linear, 0.18),
    "UNSPECIFIED": TransferFunction(srgb_to_linear, srgb_from_linear, 0.18),
    "BT_470_M": TransferFunction(gamma22_to_linear, gamma22_from_linear, 0.18),
    "BT_470_B_G": TransferFunction(gamma28_to_linear, gamma28_from_linear, 0.18),
}


def _lerp(y0: float, y1: float, x0: int, x1: int, x: int) -> float:
    if x1 == x0:
        return float(y0)
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def interpolate_scaling(xs: list[int], ys: list[int], luma: int) -> float:
    """Piecewise-linear scaling curve interpolation at arbitrary luma value."""
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


def build_scaling_lut(xs: list[int], ys: list[int]) -> list[int]:
    """Build the 256-entry integer ScalingLut as defined in AFGS1 spec section 8.2.4."""
    lut: list[int] = [0] * 256
    if not xs or not ys:
        return lut

    num_points = len(xs)
    for i in range(xs[0]):
        lut[i] = ys[0]

    for i in range(num_points - 1):
        x0, y0 = xs[i], ys[i]
        x1, y1 = xs[i + 1], ys[i + 1]
        delta_x = x1 - x0
        delta_y = y1 - y0
        if delta_x <= 0:
            continue
        delta = delta_y * ((65536 + (delta_x >> 1)) // delta_x)
        for x in range(delta_x):
            lut[x0 + x] = y0 + ((x * delta + 32768) >> 16)

    for i in range(xs[-1], 256):
        lut[i] = ys[-1]

    return lut


def compute_safe_anti_clipping_envelope(
    luma_min: int = -60,
    luma_max: int = 60,
    scaling_shift: int = 8,
    grain_scale_shift: int = 0,
    is_full_range: bool = False,
    is_chroma: bool = False,
) -> list[float]:
    total_shift = scaling_shift + grain_scale_shift
    divisor = 1 << total_shift

    abs_min = abs(luma_min) if luma_min != 0 else 1
    abs_max = abs(luma_max) if luma_max != 0 else 1

    l_min = 0 if is_full_range else 16
    l_max = 255 if is_full_range else (240 if is_chroma else 235)

    safe_envelope = [0.0] * 256
    for x in range(256):
        if x <= l_min or x >= l_max:
            safe_envelope[x] = 0.0
        else:
            y_black = ((x - l_min) * divisor) / abs_min
            y_white = ((l_max - x) * divisor) / abs_max
            safe_envelope[x] = max(0.0, min(255.0, y_black, y_white))

    return safe_envelope


class _FilmFormatsDict(dict):

    def __getitem__(self, key):
        if super().__contains__(key):
            return super().__getitem__(key)
        k_norm = str(key).strip().lower().replace("_", " ")
        for k, v in self.items():
            if k.lower().replace("_", " ") == k_norm:
                return v
        return super().__getitem__(key)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key):
        if super().__contains__(key):
            return True
        k_norm = str(key).strip().lower().replace("_", " ")
        for k in self.keys():
            if k.lower().replace("_", " ") == k_norm:
                return True
        return False


# Physical format mapping (Width, Height, EQE, PRNU, IRRN)
FILM_FORMATS = _FilmFormatsDict({
    "8mm": (4500.0, 3300.0, 0.20, 0.005, 1.5),  # Standard 8mm (Extreme grain)
    "super8": (5790.0, 4010.0, 0.20, 0.005, 1.5),  # Super 8mm
    "16mm": (10260.0, 7490.0, 0.20, 0.005, 1.5),  # Standard 16mm
    "super16": (12520.0, 7410.0, 0.20, 0.005, 1.5),  # Super 16mm
    "mft": (17300.0, 13000.0, 0.20, 0.005, 1.5),  # Micro 4/3 / 110 Format
    "super35": (24890.0, 18660.0, 0.20, 0.005, 1.5),  # Super 35 / Digital APS-C Format
    "35mm": (36000.0, 24000.0, 0.20, 0.005, 1.5),  # 35mm Photo / VistaVision / FF (Default)
    "65mm": (52480.0, 23010.0, 0.20, 0.005, 1.5),  # 65mm 5-perf
    "imax": (70410.0, 52630.0, 0.20, 0.005, 1.5),  # IMAX 15/70mm (matched Vision3 emulsion)
    "arri alexa 65": (54120.0, 25580.0, 0.30, 0.005, 1.5),  # ARRI Alexa 65
})


# AFGS1 Canonical Field Definitions & Defaults
P_FIELDS = [
    "ar_coeff_lag",
    "ar_coeff_shift",
    "grain_scale_shift",
    "scaling_shift",
    "chroma_scaling_from_luma",
    "overlap_flag",
    "cb_mult",
    "cb_luma_mult",
    "cb_offset",
    "cr_mult",
    "cr_luma_mult",
    "cr_offset",
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


def p_params_to_tokens(p: dict) -> list[str]:
    return [str(p.get(f, P_DEFAULTS[f])) for f in P_FIELDS]


def _expected_ar_count(ar_coeff_lag: int, prefix: str) -> int:
    spatial = 2 * ar_coeff_lag * (ar_coeff_lag + 1)
    if prefix.lower() in ("ccb", "ccr", "cb", "cr"):
        return spatial + 1
    return spatial


def format_c_line(prefix: str, coeffs: list[int] | None, lag: int) -> str:
    pref_lower = prefix.lower()
    if pref_lower in ("cb", "ccb"):
        canonical_prefix = "cCb"
    elif pref_lower in ("cr", "ccr"):
        canonical_prefix = "cCr"
    elif pref_lower in ("y", "cy"):
        canonical_prefix = "cY"
    else:
        canonical_prefix = prefix if prefix.startswith("c") else f"c{prefix}"
    expected_count = _expected_ar_count(lag, canonical_prefix)
    if expected_count == 0:
        return f"\t{canonical_prefix}\n"

    clamped_coeffs = [max(-128, min(127, int(c))) for c in (coeffs or [])]
    str_coeffs = [str(c) for c in clamped_coeffs]

    if len(str_coeffs) == 1 and str_coeffs[0] == "0" and expected_count > 1:
        str_coeffs = ["0"] * expected_count
    elif len(str_coeffs) < expected_count:
        str_coeffs.extend(["0"] * (expected_count - len(str_coeffs)))
    elif len(str_coeffs) > expected_count:
        str_coeffs = str_coeffs[:expected_count]

    if not str_coeffs:
        str_coeffs = ["0"] * expected_count

    return f"\t{canonical_prefix} " + " ".join(str_coeffs) + "\n"


def _build_p_line(p_params: dict) -> str:
    tokens = p_params_to_tokens(p_params)
    return "\tp " + " ".join(tokens) + "\n"


def _build_scale_line(
    prefix: str,
    data: dict | list[tuple[int, int]] | None,
    chroma_from_luma: bool = False,
) -> str:
    max_pts = 14 if prefix == "sY" else 10

    if chroma_from_luma and prefix in ("sCb", "sCr"):
        return f"\t{prefix} 0\n"

    if data is None:
        return f"\t{prefix} 0\n"

    if isinstance(data, dict):
        raw_x = data.get("x", [])
        raw_y = data.get("y", [])
        input_pairs = list(zip(raw_x, raw_y))
    else:
        input_pairs = list(data)

    pairs = []
    seen_x = set()
    for x, y in sorted(input_pairs, key=lambda pt: pt[0]):
        cx = max(0, min(255, int(x)))
        cy = max(0, min(255, int(y)))
        if cx not in seen_x:
            seen_x.add(cx)
            pairs.append((cx, cy))

    if len(pairs) > max_pts:
        pairs = pairs[: max_pts - 1] + [pairs[-1]]

    pts = len(pairs)
    if pts == 0:
        return f"\t{prefix} 0\n"
    if pts == 1:
        cx, cy = pairs[0]
        if cx > 150:
            new_x = max(0, cx - 1)
            pairs = [(new_x, cy), (cx, cy)]
        else:
            new_x = min(255, cx + 1)
            pairs = [(cx, cy), (new_x, cy)]
        pts = 2

    flat_pairs = []
    for x, y in pairs:
        flat_pairs.extend([str(x), str(y)])

    return f"\t{prefix} {pts} " + " ".join(flat_pairs) + "\n"


class PhotonNoiseGenerator:
    def __init__(
        self,
        width,
        height,
        iso_setting,
        tc_name="SRGB",
        color_range="LIMITED",
        chroma_scaling=0,
        film_format="35mm",
    ):
        self.width = width
        self.height = height
        self.iso_setting = iso_setting
        self.tf = TFS.get(str(tc_name).upper().strip(), TFS["SRGB"])
        self.color_range = str(color_range).upper().strip()
        self.chroma_scaling = int(chroma_scaling)
        self.film_format = str(film_format).lower().strip().replace("_", " ")

    def _eval_noise_at_x(
        self,
        x_norm,
        max_electrons_per_pixel,
        input_referred_read_noise,
        photo_response_non_uniformity,
        val_range,
    ):
        linear = min(1.0, max(0.0, self.tf.to_linear(x_norm)))
        electrons_per_pixel = max_electrons_per_pixel * linear

        noise_in_electrons = math.sqrt(
            input_referred_read_noise**2
            + electrons_per_pixel
            + (photo_response_non_uniformity**2 * electrons_per_pixel**2)
        )

        linear_noise = noise_in_electrons / max_electrons_per_pixel
        linear_range_start = max(0.0, linear - 2.0 * linear_noise)
        linear_range_end = min(1.0, linear + 2.0 * linear_noise)

        slope_denom = linear_range_end - linear_range_start
        if slope_denom > 1e-12:
            tf_slope = (
                self.tf.from_linear(linear_range_end)
                - self.tf.from_linear(linear_range_start)
            ) / slope_denom
        else:
            tf_slope = 0.0

        encoded_noise = linear_noise * tf_slope
        return min(255.0, val_range * 7.88 * encoded_noise)

    def generate_points(
        self,
        num_points=None,
        ramp_low=3,
        ramp_high=3,
        safe_envelope=None,
        is_chroma=False,
        chroma_gain=1.0,
    ):
        max_allowed_pts = 10 if is_chroma else 14
        if num_points is None:
            num_points = max_allowed_pts
        num_points = max(4, min(max_allowed_pts, int(num_points)))

        photons_per_lxs_per_um2 = 11260.0

        fmt = FILM_FORMATS.get(self.film_format, FILM_FORMATS["35mm"])
        (
            sensor_w,
            sensor_h,
            effective_quantum_efficiency,
            photo_response_non_uniformity,
            input_referred_read_noise,
        ) = fmt

        mid_tone_exposure = 10.0 / self.iso_setting
        pixel_area_um2 = (sensor_w * sensor_h) / (self.width * self.height)

        mid_tone_electrons_per_pixel = (
            effective_quantum_efficiency
            * photons_per_lxs_per_um2
            * mid_tone_exposure
            * pixel_area_um2
        )
        max_electrons_per_pixel = mid_tone_electrons_per_pixel / self.tf.mid_tone

        if self.color_range == "LIMITED":
            min_value = 16
            max_value = 240 if is_chroma else 235
        else:
            min_value = 0
            max_value = 255
        val_range = max_value - min_value

        if safe_envelope is not None:
            # When a full 256-entry anti-clipping envelope is provided, evaluate across
            # the entire [min_value, max_value] domain with hard 0 anchors at the ends.
            # This allows the PWL decimator to automatically place a single node right at
            # the intersection knee between the linear envelope and the physical noise curve.
            dense_x = list(range(min_value, max_value + 1))
            dense_y = []
            for x in dense_x:
                if x == min_value or x == max_value:
                    dense_y.append(0.0)
                else:
                    y_phys = (
                        self._eval_noise_at_x(
                            (x - min_value) / float(val_range),
                            max_electrons_per_pixel,
                            input_referred_read_noise,
                            photo_response_non_uniformity,
                            val_range,
                        )
                        * chroma_gain
                    )
                    y_phys = min(255.0, max(0.0, y_phys))
                    if x < len(safe_envelope):
                        y_phys = min(y_phys, float(safe_envelope[x]))
                    dense_y.append(y_phys)
            target_count = min(num_points, len(dense_x))
        else:
            x_start = min_value + max(1, int(ramp_low))
            x_end = max_value - max(1, int(ramp_high))
            if x_start >= x_end:
                x_start = min_value + 1
                x_end = max_value - 1

            dense_x = list(range(x_start, x_end + 1))
            dense_y = [
                min(
                    255.0,
                    max(
                        0.0,
                        self._eval_noise_at_x(
                            (x - min_value) / float(val_range),
                            max_electrons_per_pixel,
                            input_referred_read_noise,
                            photo_response_non_uniformity,
                            val_range,
                        )
                        * chroma_gain,
                    ),
                )
                for x in dense_x
            ]
            target_count = max(2, min(num_points - 2, len(dense_x)))

        dense_y_int = [int(round(y)) for y in dense_y]
        active_indices = list(range(len(dense_x)))

        def segment_sse(idx_l, idx_r):
            x0, y0_int = dense_x[idx_l], dense_y_int[idx_l]
            x1, y1_int = dense_x[idx_r], dense_y_int[idx_r]
            y0_f, y1_f = dense_y[idx_l], dense_y[idx_r]
            dx = x1 - x0
            if dx <= 0:
                return 0.0
            dy_int = y1_int - y0_int
            delta = dy_int * ((65536 + (dx >> 1)) // dx)
            slope_f = (y1_f - y0_f) / dx
            sse = 0.0
            for k in range(idx_l + 1, idx_r):
                offset_x = dense_x[k] - x0
                # Exact integer ScalingLut value reconstructed by the AV1 decoder (AFGS1 8.2.4)
                lut_val = y0_int + ((offset_x * delta + 32768) >> 16)
                interp_f = y0_f + offset_x * slope_f
                err_lut = dense_y_int[k] - lut_val
                err_f = dense_y[k] - interp_f
                sse += err_lut * err_lut + 0.25 * (err_f * err_f)
            return sse

        def removal_cost(pos):
            idx_prev = active_indices[pos - 1]
            idx_curr = active_indices[pos]
            idx_next = active_indices[pos + 1]
            delta = segment_sse(idx_prev, idx_next) - (
                segment_sse(idx_prev, idx_curr) + segment_sse(idx_curr, idx_next)
            )
            return max(0.0, delta)

        costs = [0.0] * len(active_indices)
        for p in range(1, len(active_indices) - 1):
            costs[p] = removal_cost(p)

        while len(active_indices) > target_count and len(active_indices) > 2:
            best_p = min(
                range(1, len(active_indices) - 1),
                key=lambda p: (
                    round(costs[p], 9),
                    dense_x[active_indices[p + 1]] - dense_x[active_indices[p - 1]],
                ),
            )
            active_indices.pop(best_p)
            costs.pop(best_p)

            if best_p - 1 >= 1:
                costs[best_p - 1] = removal_cost(best_p - 1)
            if best_p < len(active_indices) - 1:
                costs[best_p] = removal_cost(best_p)

        if safe_envelope is not None:
            scaling_points = [
                (dense_x[idx], dense_y_int[idx]) for idx in active_indices
            ]
            scaling_points[0] = (min_value, 0)
            scaling_points[-1] = (max_value, 0)
        else:
            scaling_points = [(min_value, 0)]
            for idx in active_indices:
                scaling_points.append((dense_x[idx], dense_y_int[idx]))
            scaling_points.append((max_value, 0))

        return scaling_points

    def generate_chroma_points(
        self,
        num_points=10,
        ramp_low=3,
        ramp_high=3,
        safe_envelope=None,
        chroma_gain=1.0,
    ):
        """Generate up to 10 scaling points for chroma planes (sCb / sCr)."""
        return self.generate_points(
            num_points=num_points,
            ramp_low=ramp_low,
            ramp_high=ramp_high,
            safe_envelope=safe_envelope,
            is_chroma=True,
            chroma_gain=chroma_gain,
        )

    def generate(
        self,
        num_points=14,
        ramp_low=3,
        ramp_high=3,
        safe_envelope=None,
        seed=7391,
        duration_ticks=10000000,
        scaling_points_cb=None,
        scaling_points_cr=None,
    ):
        scaling_points_y = self.generate_points(
            num_points=num_points,
            ramp_low=ramp_low,
            ramp_high=ramp_high,
            safe_envelope=safe_envelope,
            is_chroma=False,
        )
        return self._format_filmgrn1(
            scaling_points_y,
            scaling_points_cb=scaling_points_cb,
            scaling_points_cr=scaling_points_cr,
            seed=seed,
            duration_ticks=duration_ticks,
        )

    def _format_filmgrn1(
        self,
        scaling_points_y,
        scaling_points_cb=None,
        scaling_points_cr=None,
        seed=7391,
        duration_ticks=10000000,
    ):
        p_params = dict(P_DEFAULTS)
        p_params["ar_coeff_lag"] = 0
        p_params["ar_coeff_shift"] = 6
        p_params["grain_scale_shift"] = 0
        p_params["scaling_shift"] = 8
        p_params["chroma_scaling_from_luma"] = 1 if self.chroma_scaling else 0
        p_params["overlap_flag"] = 1
        p_params["cb_mult"] = 128
        p_params["cb_luma_mult"] = 128
        p_params["cb_offset"] = 256
        p_params["cr_mult"] = 128
        p_params["cr_luma_mult"] = 128
        p_params["cr_offset"] = 256

        p_line = _build_p_line(p_params)

        chroma_from_luma = bool(self.chroma_scaling)
        sy_line = _build_scale_line("sY", scaling_points_y, chroma_from_luma=False)
        scb_line = _build_scale_line("sCb", scaling_points_cb, chroma_from_luma=chroma_from_luma)
        scr_line = _build_scale_line("sCr", scaling_points_cr, chroma_from_luma=chroma_from_luma)

        cy_line = format_c_line("cY", [], 0)
        ccb_line = format_c_line("cCb", [0], 0)
        ccr_line = format_c_line("cCr", [0], 0)

        lines = [
            "filmgrn1\n",
            f"E 0 {duration_ticks} 1 {seed} 1\n",
            p_line,
            sy_line,
            scb_line,
            scr_line,
            cy_line,
            ccb_line,
            ccr_line,
        ]
        return "".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SVT-AV1 Photon Noise FGS Generator (Standalone Python)"
    )
    parser.add_argument(
        "-w",
        "--width",
        type=int,
        required=True,
        help="Source width",
    )
    parser.add_argument("-H", "--height", type=int, required=True, help="Source height")
    parser.add_argument(
        "-i",
        "--iso",
        type=int,
        required=True,
        help="Photon Noise ISO Strength (e.g. 100, 400, 3200)",
    )
    parser.add_argument(
        "-t",
        "--transfer",
        type=str,
        default="BT_709",
        choices=list(TFS.keys()),
        help="Color Space / Transfer Function",
    )
    parser.add_argument(
        "-r",
        "--range",
        type=str,
        default="LIMITED",
        choices=["LIMITED", "FULL"],
        help="Color Range (Limited vs Full)",
    )

    parser.add_argument(
        "-l",
        "--lens",
        type=str,
        default="35mm",
        help="Lens type / film format (e.g. 35mm, super35, 'ARRI Alexa 65')",
    )

    parser.add_argument(
        "-c",
        "--chroma-scaling",
        type=int,
        default=0,
        choices=[0, 1],
        help="Enable chroma scaling from luma (0 or 1)",
    )
    parser.add_argument(
        "-p",
        "--num-points",
        type=int,
        default=14,
        help="Number of luma scaling points (max 14 for luma, max 10 for chroma)",
    )
    parser.add_argument(
        "--ramp-low",
        type=int,
        default=3,
        help="Safety ramp low margin (anti-clipping)",
    )
    parser.add_argument(
        "--ramp-high",
        type=int,
        default=3,
        help="Safety ramp high margin (anti-clipping)",
    )
    parser.add_argument(
        "-s",
        "--seed",
        type=int,
        default=7391,
        help="Film grain random seed (default: 7391)",
    )
    parser.add_argument(
        "-d",
        "--duration",
        type=int,
        default=10000000,
        help="Event duration in ticks (default: 10000000)",
    )

    args = parser.parse_args()

    generator = PhotonNoiseGenerator(
        width=args.width,
        height=args.height,
        iso_setting=args.iso,
        tc_name=args.transfer,
        color_range=args.range,
        chroma_scaling=args.chroma_scaling,
        film_format=args.lens,
    )

    sys.stdout.write(
        generator.generate(
            num_points=args.num_points,
            ramp_low=args.ramp_low,
            ramp_high=args.ramp_high,
            seed=args.seed,
            duration_ticks=args.duration,
        )
    )