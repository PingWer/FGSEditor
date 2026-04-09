from __future__ import annotations
import os
import sys


def _get_table_dir() -> str:
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.join(os.path.dirname(__file__), "..")
    return os.path.normpath(os.path.join(base, "FGS_size_table"))


_TABLE_DIR = _get_table_dir()


def _parse_coeffs(line: str) -> list[int]:
    tokens = line.strip().split()
    if not tokens:
        return []
    start = 0
    if tokens[0] in ("cY", "cCb", "cCr"):
        start = 1
    result = []
    for t in tokens[start:]:
        t = t.rstrip(".,;")
        try:
            result.append(int(t))
        except ValueError:
            pass
    return result


def _parse_p_tokens(line: str) -> list[str]:
    tokens = line.strip().split()
    if tokens and tokens[0] == "p":
        return tokens[1:]
    return tokens


def load_size_preset(size_index: int) -> dict | None:
    """
    Load a grain-size preset from FGS_size_table/<size_index>.txt.
    Returns a dict with keys:
        'p_tokens'  : list[str]   – raw p-row tokens
        'cY'        : list[int]
        'cCb'       : list[int]
        'cCr'       : list[int]
    Returns None if the file does not exist.
    """
    if not os.path.isdir(_TABLE_DIR):
        return None
    path = os.path.join(_TABLE_DIR, f"{size_index}.txt")
    if not os.path.isfile(path):
        return None

    preset: dict = {"p_tokens": [], "cY": [], "cCb": [], "cCr": []}

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            tokens = line.split()
            if not tokens:
                continue
            prefix = tokens[0]
            if prefix == "p":
                preset["p_tokens"] = tokens[1:]
            elif prefix == "cY":
                preset["cY"] = _parse_coeffs(line)
            elif prefix == "cCb":
                preset["cCb"] = _parse_coeffs(line)
            elif prefix == "cCr":
                preset["cCr"] = _parse_coeffs(line)

    return preset


def available_sizes() -> list[int]:
    if not os.path.isdir(_TABLE_DIR):
        return []
    sizes = []
    for fname in os.listdir(_TABLE_DIR):
        base, ext = os.path.splitext(fname)
        if ext == ".txt":
            try:
                sizes.append(int(base))
            except ValueError:
                pass
    return sorted(sizes)


def apply_size_preset_to_event(event: dict, size_index: int) -> bool:
    if "original_raw_lines" not in event:
        event["original_raw_lines"] = list(event.get("raw_lines", []))
    if "original_p_params" not in event:
        p_val = event.get("p_params")
        if p_val:
            event["original_p_params"] = dict(p_val)

    if size_index == -1:
        event["raw_lines"] = list(event.get("original_raw_lines", []))
        if "original_p_params" in event:
            event["p_params"] = dict(event["original_p_params"])
        return True

    preset = load_size_preset(size_index)
    if preset is None:
        return False

    new_raw_lines = []

    preset_p = None
    if preset["p_tokens"]:
        from .fgs_math import parse_p_row

        preset_p = parse_p_row(preset["p_tokens"])

    for raw_line in event.get("raw_lines", []):
        tokens = raw_line.strip().split()
        if not tokens:
            new_raw_lines.append(raw_line)
            continue
        prefix = tokens[0]
        if prefix == "p" and preset_p:
            # We want to keep user's manual params (scaling_shift etc)
            # but update AR lag and shift from the preset.
            from .fgs_math import p_params_to_tokens

            current_p = dict(event.get("p_params", event.get("original_p_params", {})))
            current_p["ar_coeff_lag"] = preset_p["ar_coeff_lag"]
            current_p["ar_coeff_shift"] = preset_p["ar_coeff_shift"]
            new_tokens = p_params_to_tokens(current_p)
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

    return True
