from __future__ import annotations
import os
from .app_paths import get_base_dir
from . import fgs_parser
from .fgs_parser import load_grain_preset

_TABLE_DIR = os.path.normpath(os.path.join(get_base_dir(), "FGS_grain_size"))


def apply_grain_preset_to_event(event: dict, name: str | None) -> bool:
    if "original_raw_lines" not in event:
        event["original_raw_lines"] = list(event.get("raw_lines", []))
    if "original_p_params" not in event:
        p_val = fgs_parser.get_p_params(event)
        event["original_p_params"] = dict(p_val)

    if name is None or name == "-1":
        event["raw_lines"] = list(event.get("original_raw_lines", []))
        if "original_p_params" in event:
            event["p_params"] = dict(event["original_p_params"])
        from .fgs_parser import _parse_scale_from_lines

        event["scale_data"] = _parse_scale_from_lines(event.get("raw_lines", []))
        return True

    preset = load_grain_preset(name)
    if preset is None:
        return False

    new_raw_lines = []

    preset_p = None
    if preset["p_tokens"]:
        preset_p = fgs_parser.parse_p_row(preset["p_tokens"])

    for raw_line in event.get("raw_lines", []):
        tokens = raw_line.strip().split()
        if not tokens:
            new_raw_lines.append(raw_line)
            continue
        prefix = tokens[0]
        if prefix == "p" and preset_p:
            current_p = dict(fgs_parser.get_p_params(event))
            current_p["ar_coeff_lag"] = preset_p["ar_coeff_lag"]
            current_p["ar_coeff_shift"] = preset_p["ar_coeff_shift"]
            new_tokens = fgs_parser.p_params_to_tokens(current_p)
            new_raw_lines.append("  p " + " ".join(new_tokens) + "\n")
        elif prefix == "cY":
            coeffs = preset.get("cY", [])
            new_raw_lines.append("  cY " + " ".join(str(c) for c in coeffs) + "\n")
        elif prefix == "cCb":
            coeffs = preset.get("cCb", [])
            new_raw_lines.append("  cCb " + " ".join(str(c) for c in coeffs) + "\n")
        elif prefix == "cCr":
            coeffs = preset.get("cCr", [])
            new_raw_lines.append("  cCr " + " ".join(str(c) for c in coeffs) + "\n")
        else:
            new_raw_lines.append(raw_line)

    event["raw_lines"] = new_raw_lines

    if preset_p:
        if "p_params" not in event or event["p_params"] is None:
            event["p_params"] = dict(preset_p)
        else:
            event["p_params"]["ar_coeff_lag"] = preset_p["ar_coeff_lag"]
            event["p_params"]["ar_coeff_shift"] = preset_p["ar_coeff_shift"]

    from .fgs_parser import _parse_scale_from_lines

    event["scale_data"] = _parse_scale_from_lines(new_raw_lines)

    return True
