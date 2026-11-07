import os
import sys
import struct
import random

from fgseditor_qt.core.AFGS_TABLE_and_SEEDS import CHERRY_SEEDS



def parse_and_pack(input_file, output_file, fps=24.0, fallback_frames=150000, static_mode=False):
    with open(input_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]

    filmgrn_idx = None
    for idx, line in enumerate(lines):
        if line.lower() == "filmgrn1":
            filmgrn_idx = idx
            break

    if filmgrn_idx is None:
        print("Error: Invalid filmgrn1 format.")
        return False

    lines = lines[filmgrn_idx:]

    events = []
    current_event = []
    for line in lines[1:]:
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "E":
            if current_event:
                events.append(current_event)
            current_event = [line]
        else:
            if current_event:
                current_event.append(line)

    if current_event:
        events.append(current_event)

    bin_data = bytearray()

    for event_lines in events:
        params = {}
        for line in event_lines:
            parts = line.split()
            key = parts[0]
            values = [int(x) for x in parts[1:]]

            if key == "E":
                params["start_time"] = values[0] if len(values) > 0 else 0
                params["end_time"] = values[1] if len(values) > 1 else 0
                params["apply_grain"] = values[2] if len(values) > 2 else 1
                params["random_seed"] = values[3] if len(values) > 3 else 7391
                params["update_parameters"] = values[4] if len(values) > 4 else 1
            elif key == "p":
                params["ar_coeff_lag"] = values[0] if len(values) > 0 else 0
                params["ar_coeff_shift"] = values[1] if len(values) > 1 else 6
                params["grain_scale_shift"] = values[2] if len(values) > 2 else 0
                params["scaling_shift"] = values[3] if len(values) > 3 else 8
                params["chroma_scaling_from_luma"] = values[4] if len(values) > 4 else 0
                params["overlap_flag"] = values[5] if len(values) > 5 else 1
                params["cb_mult"] = values[6] if len(values) > 6 else 128
                params["cb_luma_mult"] = values[7] if len(values) > 7 else 128
                params["cb_offset"] = values[8] if len(values) > 8 else 256
                params["cr_mult"] = values[9] if len(values) > 9 else 128
                params["cr_luma_mult"] = values[10] if len(values) > 10 else 128
                params["cr_offset"] = values[11] if len(values) > 11 else 256
                params["clip_to_restricted_range"] = (
                    values[12] if len(values) > 12 else 1
                )
            elif key == "sY":
                params["num_y_points"] = values[0]
                params["y_points"] = values[1 : 1 + values[0] * 2]
            elif key == "sCb":
                params["num_cb_points"] = values[0]
                params["cb_points"] = (
                    values[1 : 1 + values[0] * 2] if values[0] > 0 else []
                )
            elif key == "sCr":
                params["num_cr_points"] = values[0]
                params["cr_points"] = (
                    values[1 : 1 + values[0] * 2] if values[0] > 0 else []
                )
            elif key in ("cY", "Y", "cy", "y"):
                params["y_ar_coeffs"] = values
            elif key in ("cCb", "Cb", "ccb", "cb"):
                params["cb_ar_coeffs"] = values
            elif key in ("cCr", "Cr", "ccr", "cr"):
                params["cr_ar_coeffs"] = values

        start_t = params.get("start_time", 0)
        end_t = params.get("end_time", 0)

        if len(events) == 1 and (end_t <= start_t or end_t == 0):
            event_frames = fallback_frames
        else:
            dur_s = (end_t - start_t) / 10000000.0
            event_frames = max(1, round(dur_s * fps)) if end_t > start_t else 0
            if event_frames <= 0:
                continue

        out = bytearray()
        out.extend(struct.pack("<i", params.get("apply_grain", 1)))
        out.extend(struct.pack("<H", params.get("random_seed", 3)))
        out.extend(struct.pack("<i", params.get("update_parameters", 1)))

        num_y = params.get("num_y_points", 0)
        out.extend(struct.pack("<i", num_y))
        if num_y > 0:
            y_pts = params.get("y_points", [])
            for i in range(num_y):
                out.extend(struct.pack("<i", y_pts[i * 2] if i * 2 < len(y_pts) else 0))
                out.extend(
                    struct.pack("<i", y_pts[i * 2 + 1] if i * 2 + 1 < len(y_pts) else 0)
                )

        num_cb = params.get("num_cb_points", 0)
        out.extend(struct.pack("<i", num_cb))
        if num_cb > 0:
            cb_pts = params.get("cb_points", [])
            for i in range(num_cb):
                out.extend(
                    struct.pack("<i", cb_pts[i * 2] if i * 2 < len(cb_pts) else 0)
                )
                out.extend(
                    struct.pack(
                        "<i", cb_pts[i * 2 + 1] if i * 2 + 1 < len(cb_pts) else 0
                    )
                )

        num_cr = params.get("num_cr_points", 0)
        out.extend(struct.pack("<i", num_cr))
        if num_cr > 0:
            cr_pts = params.get("cr_points", [])
            for i in range(num_cr):
                out.extend(
                    struct.pack("<i", cr_pts[i * 2] if i * 2 < len(cr_pts) else 0)
                )
                out.extend(
                    struct.pack(
                        "<i", cr_pts[i * 2 + 1] if i * 2 + 1 < len(cr_pts) else 0
                    )
                )

        out.extend(struct.pack("<i", params.get("scaling_shift", 8)))
        out.extend(struct.pack("<i", params.get("ar_coeff_lag", 0)))

        if num_y > 0:
            y_ar = params.get("y_ar_coeffs", [])
            for i in range(24):
                out.extend(struct.pack("<i", y_ar[i] if i < len(y_ar) else 0))

        if num_cb > 0:
            cb_ar = params.get("cb_ar_coeffs", [])
            for i in range(25):
                out.extend(struct.pack("<i", cb_ar[i] if i < len(cb_ar) else 0))

        if num_cr > 0:
            cr_ar = params.get("cr_ar_coeffs", [])
            for i in range(25):
                out.extend(struct.pack("<i", cr_ar[i] if i < len(cr_ar) else 0))

        out.extend(struct.pack("<i", params.get("ar_coeff_shift", 6)))
        out.extend(struct.pack("<i", params.get("grain_scale_shift", 0)))

        if num_cb > 0:
            out.extend(struct.pack("<i", params.get("cb_mult", 128)))
            out.extend(struct.pack("<i", params.get("cb_luma_mult", 128)))
            out.extend(struct.pack("<i", params.get("cb_offset", 256)))

        if num_cr > 0:
            out.extend(struct.pack("<i", params.get("cr_mult", 128)))
            out.extend(struct.pack("<i", params.get("cr_luma_mult", 128)))
            out.extend(struct.pack("<i", params.get("cr_offset", 256)))

        out.extend(struct.pack("<i", params.get("overlap_flag", 1)))
        out.extend(struct.pack("<i", params.get("clip_to_restricted_range", 1)))

        valid_seeds = list(CHERRY_SEEDS)
        original_seed = params.get("random_seed", 3)
        random.seed(original_seed)
        recent_seeds = []

        for _ in range(event_frames):
            if static_mode:
                new_seed = original_seed
            else:
                new_seed = random.choice(valid_seeds)
                while new_seed in recent_seeds:
                    new_seed = random.choice(valid_seeds)

                recent_seeds.append(new_seed)
                if len(recent_seeds) > 24:
                    recent_seeds.pop(0)

            frame_data = bytearray(out)
            frame_data[4:6] = struct.pack("<H", new_seed)
            bin_data.extend(frame_data)

    tmp_out = output_file + ".tmp"
    try:
        with open(tmp_out, "wb") as f_out:
            f_out.write(bin_data)
        os.replace(tmp_out, output_file)
    finally:
        if os.path.isfile(tmp_out):
            try:
                os.remove(tmp_out)
            except OSError:
                pass

    return True


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python binary_FGS.py <input.txt> <output.bin>")
        sys.exit(1)

    parse_and_pack(sys.argv[1], sys.argv[2])
