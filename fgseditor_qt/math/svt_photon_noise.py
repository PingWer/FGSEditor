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


# Color Space <-> Linear Conversions & C-Infinity Analytical Derivatives
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


def srgb_derivative(linear):
    # C-infinity quadrature knee matching 12.92 at L = 0 and IEC 61966-2-1 power branch for L >> 0.003
    l_eff = math.hypot(max(0.0, linear), 0.003041229589675751)
    return (1.055 / 2.4) * (l_eff ** (-1.4 / 2.4))


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


def pq_derivative(linear):
    l_safe = max(1e-12, linear)
    l_m1 = l_safe**PQ_M1
    num = PQ_C1 + PQ_C2 * l_m1
    den = 1.0 + PQ_C3 * l_m1
    base = num / den
    d_base = (PQ_M1 * (l_safe ** (PQ_M1 - 1.0)) * (PQ_C2 - PQ_C1 * PQ_C3)) / (den * den)
    return PQ_M2 * (base ** (PQ_M2 - 1.0)) * d_base


# Pure ARIB STD-B67 / ITU-R BT.2100 Table 5 Container OETF (Scene-Referred, no 1.2 monitor OOTF)
HLG_MID_TONE = (26.0 / 1000.0) ** (1.0 / 1.2)


def hlg_to_linear(hlg):
    hlg = max(0.0, hlg)
    return (
        hlg * hlg / 3.0
        if hlg <= 0.5
        else (math.exp((hlg - HLG_C) / HLG_A) + HLG_B) / 12.0
    )


def hlg_from_linear(linear):
    linear = max(0.0, linear)
    return (
        math.sqrt(3.0 * linear)
        if linear <= 1.0 / 12.0
        else HLG_A * math.log(12.0 * linear - HLG_B) + HLG_C
    )


def hlg_derivative(linear):
    # C-infinity relative-softplus transition at E = 1/12 avoiding the 0.5 OETF slope cusp
    e_safe = max(1e-12, linear)
    g1 = (2.0 / math.sqrt(3.0)) * math.sqrt(e_safe)
    g2 = (12.0 * e_safe - HLG_B) / (12.0 * HLG_A)
    diff = g2 - g1
    eps_rel = 0.08 * g1
    soft_pos = 0.5 * (diff + math.sqrt(diff * diff + eps_rel * eps_rel))
    return 1.0 / max(1e-12, g1 + soft_pos)


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


def bt601_derivative(L):
    # C-infinity quadrature knee matching 4.5 at L = 0 and 0.45 * alpha * L^-0.55 above BT709_BETA
    l_eff = math.hypot(max(0.0, L), BT709_BETA)
    return 0.45 * BT709_ALPHA * (l_eff**-0.55)


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


def smpte240m_derivative(L):
    l_eff = math.hypot(max(0.0, L), SMPTE240_BETA)
    return 0.45 * SMPTE240_ALPHA * (l_eff**-0.55)


def identity_to_linear(x):
    return x


def identity_from_linear(x):
    return x


def identity_derivative(_L):
    return 1.0


def log100_to_linear(x):
    x = max(0.0, x)
    return ((10.0 ** (x * math.log10(101.0))) - 1.0) / 100.0


def log100_from_linear(y):
    y = max(0.0, y)
    return math.log10(100.0 * y + 1.0) / math.log10(101.0)


def log100_derivative(L):
    return 100.0 / (math.log(101.0) * (100.0 * max(0.0, L) + 1.0))


def log100_sqrt10_to_linear(x):
    x = max(0.0, x)
    scale = 100.0 * 3.1622776601683795
    return ((10.0 ** (x * math.log10(scale + 1.0))) - 1.0) / scale


def log100_sqrt10_from_linear(y):
    y = max(0.0, y)
    scale = 100.0 * 3.1622776601683795
    return math.log10(scale * y + 1.0) / math.log10(scale + 1.0)


def log100_sqrt10_derivative(L):
    scale = 100.0 * 3.1622776601683795
    return scale / (math.log(scale + 1.0) * (scale * max(0.0, L) + 1.0))


def iec61966_to_linear(x):
    return bt601_to_linear(x)


def iec61966_from_linear(y):
    return bt601_from_linear(y)


def bt1361_to_linear(x):
    return bt601_to_linear(x)


def bt1361_from_linear(y):
    return bt601_from_linear(y)


# Authoring & Camera Log Working Spaces (Scene-Referred, L_mid = 0.18)
def acescct_to_linear(v):
    return (
        (v - 0.0729055341958355) / 10.5402377416545
        if v <= 0.155251141552511
        else 2.0 ** (17.52 * v - 9.72)
    )


def acescct_from_linear(L):
    L = max(0.0, L)
    return (
        10.5402377416545 * L + 0.0729055341958355
        if L <= 0.0078125
        else (math.log2(L) + 9.72) / 17.52
    )


def acescct_derivative(L):
    l_eff = math.hypot(max(0.0, L), 0.0078125)
    return 1.0 / (17.52 * math.log(2.0) * l_eff)


_DI_A = 0.0075
_DI_B = 7.0
_DI_C = 0.07329248
_DI_M = 10.44426855
_DI_LCUT = 0.00262409
_DI_VCUT = 0.02740668
_DI_DENOM_BIAS = (_DI_C / (_DI_M * math.log(2.0))) ** 2 - (_DI_A**2)


def davinci_intermediate_to_linear(v):
    return v / _DI_M if v <= _DI_VCUT else (2.0 ** (v / _DI_C - _DI_B)) - _DI_A


def davinci_intermediate_from_linear(L):
    L = max(0.0, L)
    return _DI_M * L if L <= _DI_LCUT else (math.log2(L + _DI_A) + _DI_B) * _DI_C


def davinci_intermediate_derivative(L):
    l_shift = max(0.0, L) + _DI_A
    denom = math.sqrt(l_shift * l_shift + _DI_DENOM_BIAS)
    return _DI_C / (math.log(2.0) * denom)


_LC3_A = 5.555556
_LC3_B = 0.052272
_LC3_C = 0.247190
_LC3_D = 0.385537
_LC3_E = 5.367655
_LC3_F = 0.092809
_LC3_LCUT = 0.010591
_LC3_VCUT = 0.149658
_LC3_BIAS = (_LC3_A * _LC3_LCUT + _LC3_B) ** 2 - (_LC3_B**2)


def logc3_to_linear(v):
    return (
        (v - _LC3_F) / _LC3_E
        if v <= _LC3_VCUT
        else ((10.0 ** ((v - _LC3_D) / _LC3_C)) - _LC3_B) / _LC3_A
    )


def logc3_from_linear(L):
    L = max(0.0, L)
    return (
        _LC3_E * L + _LC3_F
        if L <= _LC3_LCUT
        else _LC3_C * math.log10(_LC3_A * L + _LC3_B) + _LC3_D
    )


def logc3_derivative(L):
    u_shift = _LC3_A * max(0.0, L) + _LC3_B
    denom = math.sqrt(u_shift * u_shift + _LC3_BIAS)
    return (_LC3_C * _LC3_A) / (math.log(10.0) * denom)


_LC4_A = (2**18 - 16) / 117.45
_LC4_B = (1023.0 - 95.0) / 1023.0
_LC4_C = 95.0 / 1023.0
_LC4_S = (7.0 * math.log(2.0) * (2.0 ** (7.0 - 14.0 * _LC4_C / _LC4_B))) / (_LC4_A * _LC4_B)
_LC4_T = ((2.0 ** (6.0 - 14.0 * _LC4_C / _LC4_B)) - 64.0) / _LC4_A


def logc4_to_linear(v):
    return (
        _LC4_S * v + _LC4_T
        if v < 0.0
        else ((2.0 ** (14.0 * ((v - _LC4_C) / _LC4_B) + 6.0)) - 64.0) / _LC4_A
    )


def logc4_from_linear(L):
    return (
        (L - _LC4_T) / _LC4_S
        if L < _LC4_T
        else ((math.log2(_LC4_A * L + 64.0) - 6.0) / 14.0) * _LC4_B + _LC4_C
    )


def logc4_derivative(L):
    return (_LC4_A * _LC4_B) / (14.0 * math.log(2.0) * (_LC4_A * max(0.0, L) + 64.0))


_SL3_LCUT = 0.01125
_SL3_VCUT = 171.2102946929 / 1023.0
_SL3_BIAS = (_SL3_LCUT + 0.01) ** 2 - (0.01**2)


def slog3_to_linear(v):
    if v < _SL3_VCUT:
        return (v * 1023.0 - 95.0) * _SL3_LCUT / (171.2102946929 - 95.0)
    return (10.0 ** ((v * 1023.0 - 420.0) / 261.5)) * 0.19 - 0.01


def slog3_from_linear(L):
    L = max(0.0, L)
    if L < _SL3_LCUT:
        return (L * (171.2102946929 - 95.0) / _SL3_LCUT + 95.0) / 1023.0
    return (420.0 + 261.5 * math.log10((L + 0.01) / 0.19)) / 1023.0


def slog3_derivative(L):
    l_shift = max(0.0, L) + 0.01
    denom = math.sqrt(l_shift * l_shift + _SL3_BIAS)
    return 261.5 / (1023.0 * math.log(10.0) * denom)


_L3G10_A = 0.224282
_L3G10_B = 155.975327
_L3G10_C = 0.01
_L3G10_G = 15.1927


def log3g10_to_linear(v):
    return (
        v / _L3G10_G - _L3G10_C
        if v < 0.0
        else ((10.0 ** (v / _L3G10_A)) - 1.0) / _L3G10_B - _L3G10_C
    )


def log3g10_from_linear(L):
    return (
        (L + _L3G10_C) * _L3G10_G
        if L < -_L3G10_C
        else _L3G10_A * math.log10((L + _L3G10_C) * _L3G10_B + 1.0)
    )


def log3g10_derivative(L):
    return (_L3G10_A * _L3G10_B) / (
        math.log(10.0) * ((max(0.0, L) + _L3G10_C) * _L3G10_B + 1.0)
    )


class TransferFunction:
    def __init__(
        self,
        to_linear_fn,
        from_linear_fn,
        mid_tone,
        derivative_fn=None,
        max_linear=1.0,
        label=None,
    ):
        self.to_linear = to_linear_fn
        self.from_linear = from_linear_fn
        self.mid_tone = mid_tone
        self.derivative = derivative_fn
        self.max_linear = max_linear
        self.label = label


# Official ITU-T H.273 / CICP Video Container Transfer Functions (excluding monitor EOTFs)
CONTAINER_TFS = {
    "BT_709": TransferFunction(bt601_to_linear, bt601_from_linear, 0.18, bt601_derivative),
    "BT_2020_10_BIT (SDR)": TransferFunction(
        bt601_to_linear, bt601_from_linear, 0.18, bt601_derivative
    ),
    "BT_2020_12_BIT (SDR)": TransferFunction(
        bt601_to_linear, bt601_from_linear, 0.18, bt601_derivative
    ),
    "SMPTE_2084": TransferFunction(
        pq_to_linear, pq_from_linear, 26.0 / 10000.0, pq_derivative
    ),
    "HLG": TransferFunction(
        hlg_to_linear, hlg_from_linear, HLG_MID_TONE, hlg_derivative
    ),
    "SRGB": TransferFunction(srgb_to_linear, srgb_from_linear, 0.18, srgb_derivative),
    "BT_601": TransferFunction(bt601_to_linear, bt601_from_linear, 0.18, bt601_derivative),
    "SMPTE_240": TransferFunction(
        smpte240m_to_linear, smpte240m_from_linear, 0.18, smpte240m_derivative
    ),
    "LINEAR": TransferFunction(
        identity_to_linear, identity_from_linear, 0.50, identity_derivative
    ),
    "LOG_100": TransferFunction(
        log100_to_linear, log100_from_linear, 0.18, log100_derivative
    ),
    "LOG_100_SQRT10": TransferFunction(
        log100_sqrt10_to_linear,
        log100_sqrt10_from_linear,
        0.18,
        log100_sqrt10_derivative,
    ),
    "IEC_61966": TransferFunction(
        iec61966_to_linear, iec61966_from_linear, 0.18, bt601_derivative
    ),
    "BT_1361": TransferFunction(
        bt1361_to_linear, bt1361_from_linear, 0.18, bt601_derivative
    ),
}

# Alias for backward compatibility
TFS = CONTAINER_TFS

# Official Scene-Referred Authoring & Camera Log Working Spaces
AUTHORING_TFS = {
    "NONE": None,
    "ARRI_LOGC3": TransferFunction(
        logc3_to_linear,
        logc3_from_linear,
        0.18,
        logc3_derivative,
        max_linear=logc3_to_linear(1.0),
        label="ARRI LogC3 (EI 800)",
    ),
    "ARRI_LOGC4": TransferFunction(
        logc4_to_linear,
        logc4_from_linear,
        0.18,
        logc4_derivative,
        max_linear=logc4_to_linear(1.0),
        label="ARRI LogC4 (ALEXA 35)",
    ),
    "ACESCCT": TransferFunction(
        acescct_to_linear,
        acescct_from_linear,
        0.18,
        acescct_derivative,
        max_linear=acescct_to_linear(1.0),
        label="ACEScct (SMPTE S-2016)",
    ),
    "DAVINCI_INTERMEDIATE": TransferFunction(
        davinci_intermediate_to_linear,
        davinci_intermediate_from_linear,
        0.18,
        davinci_intermediate_derivative,
        max_linear=davinci_intermediate_to_linear(1.0),
        label="DaVinci Intermediate",
    ),
    "SONY_SLOG3": TransferFunction(
        slog3_to_linear,
        slog3_from_linear,
        0.18,
        slog3_derivative,
        max_linear=slog3_to_linear(1.0),
        label="Sony S-Log3",
    ),
    "RED_LOG3G10": TransferFunction(
        log3g10_to_linear,
        log3g10_from_linear,
        0.18,
        log3g10_derivative,
        max_linear=log3g10_to_linear(1.0),
        label="RED Log3G10 (IPP2)",
    ),
}


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


def fit_tangent_pwl(
    dense_x: list[int],
    dense_y: list[float],
    max_pts: int = 14,
    tol: float = 0.15,
    min_dx: int = 1,
) -> list[tuple[int, int]]:
    n = len(dense_x)
    if n <= 2:
        return [(dense_x[i], int(round(dense_y[i]))) for i in range(n)]

    selected_indices = [0, n - 1]

    def get_seg_split(i0, i1):
        x0, y0 = dense_x[i0], dense_y[i0]
        x1, y1 = dense_x[i1], dense_y[i1]
        dx = x1 - x0
        if dx < 2 * min_dx:
            return 0.0, None

        max_dev = 0.0
        best_k = None
        for k in range(i0 + 1, i1):
            xk = dense_x[k]
            if (xk - x0) < min_dx or (x1 - xk) < min_dx:
                continue
            y_chord = y0 + (y1 - y0) * (xk - x0) / float(dx)
            dev = abs(dense_y[k] - y_chord)
            if dev > max_dev:
                max_dev = dev
                best_k = k
        return max_dev, best_k

    while len(selected_indices) < max_pts:
        worst_dev = 0.0
        worst_k = None
        worst_seg_idx = None

        for s_idx in range(len(selected_indices) - 1):
            i0 = selected_indices[s_idx]
            i1 = selected_indices[s_idx + 1]
            dev, k = get_seg_split(i0, i1)
            if k is not None and dev > worst_dev:
                worst_dev = dev
                worst_k = k
                worst_seg_idx = s_idx

        if worst_k is None or worst_dev <= tol:
            break

        selected_indices.insert(worst_seg_idx + 1, worst_k)

    return [(dense_x[i], int(round(dense_y[i]))) for i in selected_indices]


class PhotonNoiseGenerator:
    def __init__(
        self,
        width,
        height,
        iso_setting,
        tc_name="BT_709",
        color_range="LIMITED",
        chroma_scaling=0,
        film_format="35mm",
        authoring_tc_name="NONE",
        authoring_strength=0.0,
        drt_rolloff=None,
    ):
        self.width = width
        self.height = height
        self.iso_setting = iso_setting
        self.tf = CONTAINER_TFS.get(str(tc_name).upper().strip(), CONTAINER_TFS["BT_709"])
        self.color_range = str(color_range).upper().strip()
        self.chroma_scaling = int(chroma_scaling)
        self.film_format = str(film_format).lower().strip().replace("_", " ")

        auth_key = str(authoring_tc_name or "NONE").upper().strip()
        self.authoring_tf = AUTHORING_TFS.get(auth_key)
        self.authoring_strength = (
            min(1.0, max(0.0, float(authoring_strength)))
            if self.authoring_tf is not None
            else 0.0
        )
        if drt_rolloff is None:
            self.drt_rolloff = 0.20 * self.authoring_strength
        else:
            self.drt_rolloff = min(0.50, max(0.0, float(drt_rolloff)))

        self._del_x_mid = max(1e-6, min(1.0 - 1e-6, self.tf.from_linear(self.tf.mid_tone)))

    def _compute_sensor_params(self):
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
            * 11260.0
            * mid_tone_exposure
            * pixel_area_um2
        )
        return (
            mid_tone_electrons_per_pixel,
            input_referred_read_noise,
            photo_response_non_uniformity,
        )

    def _eval_noise_at_x(
        self,
        x_norm,
        mid_tone_electrons_per_pixel,
        input_referred_read_noise,
        photo_response_non_uniformity,
        val_range,
    ):
        L_del = min(1.0, max(0.0, self.tf.to_linear(x_norm)))
        r_del = L_del / max(1e-12, self.tf.mid_tone)

        auth_tf = self.authoring_tf
        w_auth = self.authoring_strength if auth_tf is not None else 0.0

        # Smooth EMVA 1288 sensor full-well saturation clamp for authoring dynamic range limits
        if w_auth > 1e-9 and auth_tf is not None:
            r_max_auth = max(1.0, auth_tf.max_linear / max(1e-12, auth_tf.mid_tone))
            ratio = min(50.0, r_del / r_max_auth)
            r_eff = (1.0 - w_auth) * r_del + w_auth * (r_max_auth * math.tanh(ratio))
            sech2_r = 1.0 / (math.cosh(ratio) ** 2)
            sech2_mid = 1.0 / (math.cosh(1.0 / r_max_auth) ** 2)
            d_sat = (1.0 - w_auth) + w_auth * (sech2_r / sech2_mid)
        else:
            r_eff = r_del
            d_sat = 1.0

        electrons_per_pixel = mid_tone_electrons_per_pixel * r_eff
        noise_in_electrons = math.sqrt(
            input_referred_read_noise**2
            + electrons_per_pixel
            + (photo_response_non_uniformity**2 * electrons_per_pixel**2)
        )
        sigma_rel_mid = noise_in_electrons / max(1e-15, mid_tone_electrons_per_pixel)
        if sigma_rel_mid <= 1e-15:
            return 0.0

        sigma_lin_del = sigma_rel_mid * self.tf.mid_tone
        L_eff_del = min(1.0, math.hypot(L_del, 1.7 * sigma_lin_del))
        if self.tf.derivative is not None:
            j_del = self.tf.derivative(L_eff_del)
        else:
            h = max(1e-7, min(sigma_lin_del, 0.01))
            l_hi = min(1.0, L_eff_del + h)
            l_lo = max(0.0, L_eff_del - h)
            denom = l_hi - l_lo
            j_del = (
                (self.tf.from_linear(l_hi) - self.tf.from_linear(l_lo)) / denom
                if denom > 1e-12
                else 0.0
            )
        G_del = self.tf.mid_tone * max(0.0, j_del)

        if w_auth > 1e-9 and auth_tf is not None and auth_tf.derivative is not None:
            sigma_lin_auth = sigma_rel_mid * auth_tf.mid_tone
            L_scene_eff = math.hypot(auth_tf.mid_tone * r_eff, 1.7 * sigma_lin_auth)
            j_auth = auth_tf.derivative(L_scene_eff)
            G_auth = max(1e-12, auth_tf.mid_tone * j_auth * d_sat)
            G_del_safe = max(1e-12, G_del)
            blended_gain = (G_auth**w_auth) * (G_del_safe ** (1.0 - w_auth))
        else:
            blended_gain = G_del

        if self.drt_rolloff > 1e-9:
            x_mid = self._del_x_mid
            if x_norm < x_mid:
                d_mid = (x_mid - x_norm) / max(1e-9, x_mid)
            else:
                d_mid = (x_norm - x_mid) / max(1e-9, 1.0 - x_mid)
            drt_window = max(0.0, 1.0 - self.drt_rolloff * (d_mid * d_mid))
        else:
            drt_window = 1.0

        encoded_noise = sigma_rel_mid * blended_gain * drt_window
        return min(255.0, max(0.0, val_range * 7.88 * encoded_noise))

    def get_theoretical_noise_curve(
        self,
        dense_x=None,
        chroma_gain=1.0,
        num_points=3000,
        is_chroma=False,
    ):
        """Return (xs, ys) of the theoretical continuous photon noise curve in 0..255."""
        (
            mid_tone_electrons_per_pixel,
            input_referred_read_noise,
            photo_response_non_uniformity,
        ) = self._compute_sensor_params()

        min_val = 16.0 if self.color_range == "LIMITED" else 0.0
        max_val = (
            255.0
            if self.color_range != "LIMITED"
            else (240.0 if is_chroma else 235.0)
        )
        val_range = max(1e-6, max_val - min_val)

        if dense_x is None:
            num_samples = max(2000, num_points)
            step = val_range / float(num_samples - 1)
            dense_x = [min_val + i * step for i in range(num_samples)]
            dense_x[0] = min_val
            dense_x[-1] = max_val

        xs = []
        ys = []
        for x in dense_x:
            x_norm = max(0.0, min(1.0, (x - min_val) / float(val_range)))
            y_phys = (
                self._eval_noise_at_x(
                    x_norm,
                    mid_tone_electrons_per_pixel,
                    input_referred_read_noise,
                    photo_response_non_uniformity,
                    val_range,
                )
                * chroma_gain
            )
            xs.append(x)
            ys.append(min(255.0, max(0.0, y_phys)))
        if xs:
            xs[0] = min_val
            xs[-1] = max_val
        return xs, ys

    def generate_points(
        self,
        num_points=None,
        ramp_low=1,
        ramp_high=1,
        safe_envelope=None,
        is_chroma=False,
        chroma_gain=1.0,
    ):
        max_allowed_pts = 10 if is_chroma else 14
        if num_points is None:
            num_points = max_allowed_pts
        num_points = max(2, min(max_allowed_pts, int(num_points)))

        (
            mid_tone_electrons_per_pixel,
            input_referred_read_noise,
            photo_response_non_uniformity,
        ) = self._compute_sensor_params()

        if self.color_range == "LIMITED":
            min_value = 16
            max_value = 240 if is_chroma else 235
        else:
            min_value = 0
            max_value = 255
        val_range = max_value - min_value

        x_start = min_value + max(1, int(ramp_low))
        x_end = max_value - max(1, int(ramp_high))
        if x_start >= x_end:
            x_start = min_value + 1
            x_end = max_value - 1

        dense_x = list(range(x_start, x_end + 1))
        dense_y = []
        for x in dense_x:
            y_phys = (
                self._eval_noise_at_x(
                    (x - min_value) / float(val_range),
                    mid_tone_electrons_per_pixel,
                    input_referred_read_noise,
                    photo_response_non_uniformity,
                    val_range,
                )
                * chroma_gain
            )
            y_phys = min(255.0, max(0.0, y_phys))
            if safe_envelope is not None and x < len(safe_envelope):
                y_phys = min(y_phys, float(safe_envelope[x]))
            dense_y.append(y_phys)

        mid_pts = fit_tangent_pwl(
            dense_x, dense_y, max_pts=max(2, num_points - 2), tol=0.15, min_dx=1
        )
        scaling_points = [(min_value, 0)] + mid_pts + [(max_value, 0)]

        cleaned = []
        seen_x = set()
        for x, y in sorted(scaling_points, key=lambda pt: pt[0]):
            cx = max(min_value, min(max_value, int(x)))
            cy = max(0, min(255, int(y)))
            if cx not in seen_x:
                seen_x.add(cx)
                cleaned.append((cx, cy))

        if len(cleaned) > max_allowed_pts:
            cleaned = cleaned[: max_allowed_pts - 1] + [cleaned[-1]]

        return cleaned

    def generate_chroma_points(
        self,
        num_points=10,
        ramp_low=1,
        ramp_high=1,
        safe_envelope=None,
        chroma_gain=1.0,
    ):
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
        ramp_low=1,
        ramp_high=1,
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
        "-a",
        "--authoring-transfer",
        type=str,
        default="NONE",
        choices=list(AUTHORING_TFS.keys()),
        help="Camera / DI authoring Log working space (default: NONE = Direct Container Transfer)",
    )
    parser.add_argument(
        "-m",
        "--authoring-strength",
        "--authoring-mix",
        dest="authoring_strength",
        type=float,
        default=0.0,
        help="Authoring Log influence in [0.0, 1.0] (0=Direct, 0.5=Hybrid, 1.0=Pure Log)",
    )
    parser.add_argument(
        "--drt-rolloff",
        type=float,
        default=None,
        help="DRT Toe/Clip roll-off in [0.0, 0.5] (default: adaptive 0.20 * authoring-strength)",
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
        authoring_tc_name=args.authoring_transfer,
        authoring_strength=args.authoring_strength,
        drt_rolloff=args.drt_rolloff,
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