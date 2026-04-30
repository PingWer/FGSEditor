from .fgs_math import natural_sort_key

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


def extract_ar_coeffs_from_raw_lines(
    raw_lines: list[str],
) -> tuple[list[int], list[int], list[int]]:
    return (
        _extract_coeffs(raw_lines, "cY"),
        _extract_coeffs(raw_lines, "cCb"),
        _extract_coeffs(raw_lines, "cCr"),
    )


def get_p_params(ctx: dict) -> dict:
    if "ar_coeff_lag" in ctx:
        return ctx
    p = ctx.get("p_params")
    if p is not None:
        return p
    # Fallback: scan raw_lines if available
    for line in ctx.get("raw_lines", []):
        tokens = line.strip().split()
        if tokens and tokens[0] == "p":
            return parse_p_row(tokens[1:])
    return P_DEFAULTS


def get_grain_size(ctx: dict) -> str:
    gs = ctx.get("grain_size")
    if gs is not None:
        return str(gs)
    p = ctx.get("p_params")
    if p and "grain_size" in p:
        return str(p["grain_size"])
    return "-1"  # Default to Manual/Original


def get_scale_data(event: dict) -> dict:
    return event.get("scale_data") or {
        "sY": {"x": [], "y": []},
        "sCb": {"x": [], "y": []},
        "sCr": {"x": [], "y": []},
    }


def get_scaling_shift(event: dict) -> int:
    return get_p_params(event).get("scaling_shift", P_DEFAULTS["scaling_shift"])


def get_ar_coeff_shift(event: dict) -> int:
    return get_p_params(event).get("ar_coeff_shift", P_DEFAULTS["ar_coeff_shift"])


def get_sY_values(event: dict) -> list[int]:
    scale_data = event.get("scale_data", {})
    return scale_data.get("sY", {}).get("y", [])


def get_sCb_values(event: dict) -> list[int]:
    scale_data = event.get("scale_data", {})
    return scale_data.get("sCb", {}).get("y", [])


def get_sCr_values(event: dict) -> list[int]:
    scale_data = event.get("scale_data", {})
    return scale_data.get("sCr", {}).get("y", [])


def get_grain_scale_shift(event: dict) -> int:
    return get_p_params(event).get("grain_scale_shift", P_DEFAULTS["grain_scale_shift"])


def get_chroma_scaling_from_luma(event: dict) -> int:
    return get_p_params(event).get(
        "chroma_scaling_from_luma", P_DEFAULTS["chroma_scaling_from_luma"]
    )


def get_cb_mult(event: dict) -> int:
    return get_p_params(event).get("cb_mult", P_DEFAULTS["cb_mult"])


def get_cb_luma_mult(event: dict) -> int:
    return get_p_params(event).get("cb_luma_mult", P_DEFAULTS["cb_luma_mult"])


def get_cb_offset(event: dict) -> int:
    return get_p_params(event).get("cb_offset", P_DEFAULTS["cb_offset"])


def get_cr_mult(event: dict) -> int:
    return get_p_params(event).get("cr_mult", P_DEFAULTS["cr_mult"])


def get_cr_luma_mult(event: dict) -> int:
    return get_p_params(event).get("cr_luma_mult", P_DEFAULTS["cr_luma_mult"])


def get_cr_offset(event: dict) -> int:
    return get_p_params(event).get("cr_offset", P_DEFAULTS["cr_offset"])


def get_overlap_flag(event: dict) -> int:
    return get_p_params(event).get("overlap_flag", P_DEFAULTS["overlap_flag"])


def get_ar_coeff_lag(event: dict) -> int:
    return get_p_params(event).get("ar_coeff_lag", P_DEFAULTS["ar_coeff_lag"])


def get_grain_seed(event: dict) -> int:
    params = event.get("extra_params", [])
    if len(params) >= 2:
        try:
            return int(params[1])
        except (ValueError, TypeError):
            pass
    return 6967  # fallback default


def set_grain_seed(event: dict, seed: int) -> None:
    params = event.get("extra_params", [])
    if len(params) >= 2:
        params[1] = str(seed)
    elif len(params) == 1:
        params.append(str(seed))
    else:
        event["extra_params"] = ["1", str(seed), "1"]


def _parse_scale_from_lines(lines):
    fgs_data = {
        "sY": {"x": [], "y": []},
        "sCb": {"x": [], "y": []},
        "sCr": {"x": [], "y": []},
    }
    for line in lines:
        tokens = line.strip().split()
        if not tokens:
            continue
        prefix = tokens[0]
        if prefix in fgs_data:
            num_points = int(tokens[1])
            for i in range(num_points):
                value = int(tokens[2 + (i * 2)])
                strength = int(tokens[3 + (i * 2)])
                fgs_data[prefix]["x"].append(value)
                fgs_data[prefix]["y"].append(strength)
    return fgs_data


def _extract_p_params(raw_lines: list[str]) -> dict | None:
    for raw_line in raw_lines:
        tokens = raw_line.strip().split()
        if tokens and tokens[0] == "p":
            return parse_p_row(tokens[1:])
    return None


def parse_fgs_events(content):
    lines = content.splitlines(keepends=True)
    events = []
    header_lines = []
    current_event = None

    for line in lines:
        stripped = line.strip()
        tokens = stripped.split()

        if tokens and tokens[0] == "E":
            if current_event is not None:
                current_event["scale_data"] = _parse_scale_from_lines(
                    [line_text.strip() for line_text in current_event["raw_lines"]]
                )
                current_event["p_params"] = _extract_p_params(
                    current_event["raw_lines"]
                )
                events.append(current_event)

            start_t = int(tokens[1])
            end_t = int(tokens[2])
            current_event = {
                "start_time": start_t,
                "end_time": end_t,
                "e_line": line,
                "extra_params": tokens[3:],
                "raw_lines": [],
                "scale_data": None,
                "p_params": None,
            }
        elif current_event is not None:
            current_event["raw_lines"].append(line)
        else:
            header_lines.append(line)

    if current_event is not None:
        current_event["scale_data"] = _parse_scale_from_lines(
            [line_text.strip() for line_text in current_event["raw_lines"]]
        )
        current_event["p_params"] = _extract_p_params(current_event["raw_lines"])
        events.append(current_event)

    return header_lines, events


def is_dynamic(events):
    return len(events) > 1


def available_grain_presets() -> list[str]:
    import os
    from .app_paths import get_base_dir

    table_dir = os.path.normpath(os.path.join(get_base_dir(), "FGS_grain_size"))
    if not os.path.isdir(table_dir):
        return []
    sizes = []
    for fname in os.listdir(table_dir):
        base, ext = os.path.splitext(fname)
        if ext == ".txt":
            sizes.append(base)

    return sorted(sizes, key=natural_sort_key)


def load_grain_preset(name: str) -> dict | None:
    import os
    from .app_paths import get_base_dir

    table_dir = os.path.normpath(os.path.join(get_base_dir(), "FGS_grain_size"))

    if not os.path.isdir(table_dir):
        return None
    path = os.path.join(table_dir, f"{name}.txt")
    if not os.path.isfile(path):
        return None

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        raw_lines = fh.readlines()

    p_dict = _extract_p_params(raw_lines)
    cy, cb, cr = extract_ar_coeffs_from_raw_lines(raw_lines)

    return {
        "p_token_list": p_params_to_tokens(p_dict) if p_dict else [],
        "p_tokens": p_params_to_tokens(p_dict) if p_dict else [],  # legacy key
        "cY": cy,
        "cCb": cb,
        "cCr": cr,
    }
