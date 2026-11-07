from __future__ import annotations
from fgseditor_qt.core import fgs_parser
from fgseditor_qt.core.fgs_parser import load_grain_preset


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
        from fgseditor_qt.core.fgs_parser import _parse_scale_from_lines

        event["scale_data"] = _parse_scale_from_lines(event.get("raw_lines", []))
        return True

    preset = load_grain_preset(name)
    if preset is None:
        return False

    new_raw_lines = []

    preset_p = None
    if preset["p_tokens"]:
        preset_p = fgs_parser.parse_p_row(preset["p_tokens"])

    seen_prefixes = set()
    for raw_line in event.get("raw_lines", []):
        clean = raw_line.split("#", 1)[0].strip()
        tokens = clean.split()
        if not tokens:
            new_raw_lines.append(raw_line)
            continue
        prefix = tokens[0]
        pref_lower = prefix.lower()
        if pref_lower in ("cb", "ccb"):
            canonical_prefix = "cCb"
        elif pref_lower in ("cr", "ccr"):
            canonical_prefix = "cCr"
        elif pref_lower in ("y", "cy"):
            canonical_prefix = "cY"
        else:
            canonical_prefix = prefix

        if prefix.lower() == "p" and preset_p:
            seen_prefixes.add("p")
            current_p = dict(fgs_parser.get_p_params(event))
            current_p["ar_coeff_lag"] = preset_p["ar_coeff_lag"]
            current_p["ar_coeff_shift"] = preset_p["ar_coeff_shift"]
            new_tokens = fgs_parser.p_params_to_tokens(current_p)
            new_raw_lines.append("  p " + " ".join(new_tokens) + "\n")
        elif canonical_prefix in ("cY", "cCb", "cCr"):
            if canonical_prefix not in seen_prefixes:
                seen_prefixes.add(canonical_prefix)
                coeffs = preset.get(canonical_prefix, [])
                preset_lag = preset_p["ar_coeff_lag"] if preset_p else 3
                new_raw_lines.append(fgs_parser.format_c_line(canonical_prefix, coeffs, preset_lag))
        else:
            seen_prefixes.add(prefix)
            new_raw_lines.append(raw_line)

    for prefix in ("cY", "cCb", "cCr"):
        if prefix not in seen_prefixes:
            coeffs = preset.get(prefix, [])
            preset_lag = preset_p["ar_coeff_lag"] if preset_p else 3
            new_raw_lines.append(fgs_parser.format_c_line(prefix, coeffs, preset_lag))

    event["raw_lines"] = new_raw_lines

    if preset_p:
        if "p_params" not in event or event["p_params"] is None:
            event["p_params"] = dict(preset_p)
        else:
            event["p_params"]["ar_coeff_lag"] = preset_p["ar_coeff_lag"]
            event["p_params"]["ar_coeff_shift"] = preset_p["ar_coeff_shift"]

    from fgseditor_qt.core.fgs_parser import _parse_scale_from_lines

    event["scale_data"] = _parse_scale_from_lines(new_raw_lines)

    return True
