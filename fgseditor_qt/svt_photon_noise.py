# ==============================================================================
# Copyright(c) 2019 Intel Corporation
#
# This source code is subject to the terms of the BSD 2 Clause License and
# the Alliance for Open Media Patent License 1.0. If the BSD 2 Clause License
# was not distributed with this source code in the LICENSE file, you can
# obtain it at https://www.aomedia.org/license/software-license. If the Alliance for Open
# Media Patent License 1.0 was not distributed with this source code in the
# PATENTS file, you can obtain it at https://www.aomedia.org/license/patent-license.
#
# Python port by Michele 'PingWer' Cosentino
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


# Color Space <-> Linear Conversions
def gamma22_to_linear(g):
    return g**2.2


def gamma22_from_linear(l):  # noqa: E741
    return l ** (1.0 / 2.2)


def gamma28_to_linear(g):
    return g**2.8


def gamma28_from_linear(l):  # noqa: E741
    return l ** (1.0 / 2.8)


def gamma24_to_linear(g):
    return g**2.4


def gamma24_from_linear(l):  # noqa: E741
    return l ** (1.0 / 2.4)


def srgb_to_linear(srgb):
    return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4


def srgb_from_linear(linear):
    return (
        12.92 * linear
        if linear <= 0.0031308
        else 1.055 * (linear ** (1.0 / 2.4)) - 0.055
    )


def pq_to_linear(pq):
    pq_pow_inv_m2 = pq ** (1.0 / PQ_M2)
    num = max(0.0, pq_pow_inv_m2 - PQ_C1)
    den = PQ_C2 - PQ_C3 * pq_pow_inv_m2
    return (num / den) ** (1.0 / PQ_M1)


def pq_from_linear(linear):
    linear_pow_m1 = linear**PQ_M1
    return ((PQ_C1 + PQ_C2 * linear_pow_m1) / (1.0 + PQ_C3 * linear_pow_m1)) ** PQ_M2


def hlg_to_linear(hlg):
    linear = (
        hlg * hlg / 3.0
        if hlg <= 0.5
        else (math.exp((hlg - HLG_C) / HLG_A) + HLG_B) / 12.0
    )
    return linear**1.2


def hlg_from_linear(linear):
    linear = linear ** (1.0 / 1.2)
    return (
        math.sqrt(3.0 * linear)
        if linear <= 1.0 / 12.0
        else HLG_A * math.log(12.0 * linear - HLG_B) + HLG_C
    )


def bt601_to_linear(E):
    return E / 4.5 if E < 0.08145 else ((E + 0.099) / 1.099) ** (1.0 / 0.45)


def bt601_from_linear(L):
    return 4.5 * L if L < 0.018 else 1.099 * (L**0.45) - 0.099


def smpte240m_to_linear(x):
    return x**2.222


def smpte240m_from_linear(x):
    return x ** (1.0 / 2.222)


def identity_to_linear(x):
    return x


def identity_from_linear(x):
    return x


def log100_to_linear(x):
    return (10.0 ** (x * math.log10(101.0))) - 1.0


def log100_from_linear(y):
    return math.log10(y + 1.0) / math.log10(101.0)


def log100_sqrt10_to_linear(x):
    return (10.0 ** (x * math.log10(100.0 * 3.1622776601683795 + 1.0))) - 1.0


def log100_sqrt10_from_linear(y):
    return math.log10(y + 1.0) / math.log10(100.0 * 3.1622776601683795 + 1.0)


def iec61966_to_linear(x):
    return ((x + 0.1555) / 1.2847) ** 2.6


def iec61966_from_linear(y):
    return (y ** (1.0 / 2.6) * 1.2847) - 0.1555


def bt1361_to_linear(x):
    return x / 4.5 if x <= 0.08 else ((x + 0.099) / 1.099) ** 2.2


def bt1361_from_linear(y):
    return y * 4.5 if y <= (0.08 / 4.5) else (1.099 * (y ** (1.0 / 2.2)) - 0.099)


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

# Physical format mapping (Width, Height, EQE, PRNU, IRRN)
FILM_FORMATS = {
    "8mm": (4500.0, 3300.0, 0.20, 0.005, 1.5),  # Standard 8mm (Extreme grain)
    "super8": (5790.0, 4010.0, 0.20, 0.005, 1.5),  # Super 8mm
    "16mm": (10260.0, 7490.0, 0.20, 0.005, 1.5),  # Standard 16mm
    "super16": (12520.0, 7410.0, 0.20, 0.005, 1.5),  # Super 16mm
    "mft": (17300.0, 13000.0, 0.20, 0.005, 1.5),  # Micro 4/3 / 110 Format
    "super35": (24890.0, 18660.0, 0.20, 0.005, 1.5),  # Super 35 / Digital APS-C Format
    "35mm": (36000.0, 24000.0, 0.20, 0.005, 1.5),  # 35mm Photo / VistaVision / FF
    "65mm": (52480.0, 23010.0, 0.20, 0.005, 1.5),  # 65mm
    "imax": (70410.0, 52630.0, 0.05, 0.05, 10.0),  # IMAX 70mm
    "ARRI Alexa 65": (54120.0, 25580.0, 0.30, 0.005, 1.5),  # ARRI Alexa 65
}


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
        self.tf = TFS.get(tc_name.upper(), TFS["SRGB"])
        self.color_range = color_range.upper()
        self.chroma_scaling = chroma_scaling
        self.film_format = film_format.lower()

    def generate_points(self):
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

        max_value = 235 if self.color_range == "LIMITED" else 255
        min_value = 16 if self.color_range == "LIMITED" else 0
        val_range = max_value - min_value
        ramp_offset = 3
        num_y_points = 14

        scaling_points_y = []

        for i in range(num_y_points):
            x = (
                ramp_offset
                + (val_range - 2 * ramp_offset) * ((i - 1) / (num_y_points - 3.0))
            ) / val_range

            # Clamping at edges to avoid unnatural darkening/brightening
            if i == 0:
                x = 0
            elif i == num_y_points - 1:
                x = 1

            # Conversion to linear space and electron calculation for that luma level
            linear = self.tf.to_linear(x)
            electrons_per_pixel = max_electrons_per_pixel * linear

            # Quadrature sum of noise (Shot Noise + Read Noise + PRNU)
            noise_in_electrons = math.sqrt(
                input_referred_read_noise**2
                + electrons_per_pixel
                + (photo_response_non_uniformity**2 * electrons_per_pixel**2)
            )

            linear_noise = noise_in_electrons / max_electrons_per_pixel
            linear_range_start = max(0.0, linear - 2.0 * linear_noise)
            linear_range_end = min(1.0, linear + 2.0 * linear_noise)

            # Slope calculation to convert noise back to transfer function space
            slope_denom = linear_range_end - linear_range_start
            if slope_denom != 0:
                tf_slope = (
                    self.tf.from_linear(linear_range_end)
                    - self.tf.from_linear(linear_range_start)
                ) / slope_denom
            else:
                tf_slope = 0

            encoded_noise = linear_noise * tf_slope
            x_scaled = round(min_value + (val_range * x))

            # 8-bit AV1 quantization and safety limit
            encoded_noise_scaled = min(
                val_range, round(val_range * 7.88 * encoded_noise)
            )

            # Extreme points must be forced to 0
            if i == 0 or i == num_y_points - 1:
                scaling_points_y.append((int(x_scaled), 0))
                continue

            scaling_points_y.append((int(x_scaled), int(encoded_noise_scaled)))

        return scaling_points_y

    def generate(self):
        scaling_points_y = self.generate_points()
        return self._format_filmgrn1(scaling_points_y)

    def _format_filmgrn1(self, scaling_points_y):
        sY_str = " ".join(f"{p[0]} {p[1]}" for p in scaling_points_y)

        lines = [
            "filmgrn1",
            "E 0 18446744073709551615 1 787 1",
            "\tp 0 6 0 0 0 0 0 0 0",
            f"\tsY 14 {sY_str}",
            "\tsCb 0",
            "\tsCr 0",
        ]
        return "\n".join(lines) + "\n"


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
        choices=list(FILM_FORMATS.keys()),
        help="Lens type",
    )

    args = parser.parse_args()

    generator = PhotonNoiseGenerator(
        width=args.width,
        height=args.height,
        iso_setting=args.iso,
        tc_name=args.transfer,
        color_range=args.range,
        film_format=args.lens,
    )

    sys.stdout.write(generator.generate())
