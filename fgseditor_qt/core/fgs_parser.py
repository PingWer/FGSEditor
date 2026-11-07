from __future__ import annotations
from fgseditor_qt.math.fgs_math import natural_sort_key

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

P_RANGES = {
    "ar_coeff_lag": (0, 3),
    "ar_coeff_shift": (6, 9),
    "grain_scale_shift": (0, 3),
    "scaling_shift": (8, 11),
    "chroma_scaling_from_luma": (0, 1),
    "overlap_flag": (0, 1),
    "cb_mult": (0, 255),
    "cb_luma_mult": (0, 255),
    "cb_offset": (0, 511),
    "cr_mult": (0, 255),
    "cr_luma_mult": (0, 255),
    "cr_offset": (0, 511),
}


def _expected_ar_count(ar_coeff_lag: int, prefix: str) -> int:
    spatial = 2 * ar_coeff_lag * (ar_coeff_lag + 1)
    if prefix.lower() in ("ccb", "ccr", "cb", "cr"):
        return spatial + 1
    return spatial


def format_c_line(prefix: str, coeffs: list[int], lag: int) -> str:
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

    clamped_coeffs = [max(-128, min(127, int(c))) for c in coeffs]
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


def parse_p_row(
    tokens: list[str], event_idx: int = 1, warnings: list[str] | None = None
) -> dict:
    result = dict(P_DEFAULTS)
    if len(tokens) < len(P_FIELDS) and warnings is not None:
        warnings.append(
            f"Event {event_idx}: Line 'p' contained {len(tokens)} values (expected {len(P_FIELDS)}); populated remaining fields with standard defaults."
        )
    elif len(tokens) > len(P_FIELDS) and warnings is not None:
        warnings.append(
            f"Event {event_idx}: Line 'p' contained {len(tokens)} values (expected {len(P_FIELDS)}); excess values ignored."
        )

    for i, field in enumerate(P_FIELDS):
        if i < len(tokens):
            try:
                raw_val = int(tokens[i])
                lo, hi = P_RANGES[field]
                clamped = max(lo, min(hi, raw_val))
                if clamped != raw_val and warnings is not None:
                    warnings.append(
                        f"Event {event_idx}: Parameter '{field}' ({raw_val}) out of AFGS1 spec range [{lo}..{hi}]; clamped to {clamped}."
                    )
                result[field] = clamped
            except ValueError:
                if warnings is not None:
                    warnings.append(
                        f"Event {event_idx}: Non-integer token '{tokens[i]}' for '{field}'; used default {P_DEFAULTS[field]}."
                    )
    return result


def p_params_to_tokens(p: dict) -> list[str]:
    return [str(p.get(f, P_DEFAULTS[f])) for f in P_FIELDS]


def _extract_coeffs(raw_lines: list[str], key: str) -> list[int]:
    key_lower = key.lower()
    if key_lower in ("ccb", "cb"):
        target_keys = ("cCb", "Cb", "ccb", "cb", "CCb", "CB")
    elif key_lower in ("ccr", "cr"):
        target_keys = ("cCr", "Cr", "ccr", "cr", "CCr", "CR")
    elif key_lower in ("cy", "y"):
        target_keys = ("cY", "Y", "cy", "y", "CY")
    else:
        target_keys = (key,)

    for k in target_keys:
        for line in raw_lines:
            clean = line.split("#", 1)[0].strip()
            tokens = clean.split()
            if not tokens or tokens[0] != k:
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
    return "-1"



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
    return get_p_params(event).get(
        "grain_scale_shift", P_DEFAULTS["grain_scale_shift"]
    )


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
    return 7391


def set_grain_seed(event: dict, seed: int) -> None:
    params = event.get("extra_params", [])
    if len(params) >= 2:
        params[1] = str(seed)
    elif len(params) == 1:
        params.append(str(seed))
    else:
        event["extra_params"] = ["1", str(seed), "1"]


def _parse_scale_from_lines(
    lines: list[str], event_idx: int = 1, warnings: list[str] | None = None
) -> dict:
    fgs_data = {
        "sY": {"x": [], "y": []},
        "sCb": {"x": [], "y": []},
        "sCr": {"x": [], "y": []},
    }
    scale_prefix_map = {
        "sy": "sY",
        "scb": "sCb",
        "scr": "sCr",
    }
    for line in lines:
        clean = line.split("#", 1)[0].strip()
        tokens = clean.split()
        if not tokens:
            continue
        raw_prefix = tokens[0]
        prefix = scale_prefix_map.get(raw_prefix.lower())
        if prefix is None:
            continue
        if raw_prefix != prefix and warnings is not None:
            warnings.append(
                f"Event {event_idx}: Scale channel prefix '{raw_prefix}' normalized to canonical '{prefix}'."
            )

        raw_coords = tokens[2:] if len(tokens) > 2 else []
        declared_count = 0
        if len(tokens) > 1:
            try:
                declared_count = int(tokens[1])
            except ValueError:
                declared_count = 0

        if len(raw_coords) % 2 != 0:
            dangling = raw_coords.pop()
            if warnings is not None:
                warnings.append(
                    f"Event {event_idx}: Line '{prefix}' had an odd number of coordinates; discarded dangling value '{dangling}'."
                )

        pairs: list[tuple[int, int]] = []
        for i in range(0, len(raw_coords), 2):
            try:
                vx = int(raw_coords[i])
                vy = int(raw_coords[i + 1])
                clamped_x = max(0, min(255, vx))
                clamped_y = max(0, min(255, vy))
                pairs.append((clamped_x, clamped_y))
            except ValueError:
                pass

        if declared_count != len(pairs) and warnings is not None:
            warnings.append(
                f"Event {event_idx}: Line '{prefix}' declared {declared_count} points but contained {len(pairs)} coordinate pairs; updated count."
            )

        if pairs and pairs != sorted(pairs, key=lambda pt: pt[0]):
            pairs.sort(key=lambda pt: pt[0])
            if warnings is not None:
                warnings.append(
                    f"Event {event_idx}: Channel '{prefix}' had points re-sorted into strictly ascending X order."
                )

        deduped: list[tuple[int, int]] = []
        seen_x = set()
        for px, py in pairs:
            if px in seen_x:
                if warnings is not None:
                    warnings.append(
                        f"Event {event_idx}: Channel '{prefix}' had duplicate point at X={px}; duplicate removed."
                    )
            else:
                seen_x.add(px)
                deduped.append((px, py))

        max_pts = 14 if prefix == "sY" else 10
        if len(deduped) > max_pts:
            if warnings is not None:
                warnings.append(
                    f"Event {event_idx}: Channel '{prefix}' exceeded maximum allowed points ({len(deduped)} > {max_pts}); truncated to {max_pts} points."
                )
            deduped = deduped[:max_pts]

        if any(pt[0] < 16 or pt[0] > 235 for pt in deduped) and warnings is not None:
            warnings.append(
                f"Event {event_idx}: Channel '{prefix}' contains points outside standard TV Range (0-15 or 236-255); Full Range mode enabled."
            )

        fgs_data[prefix]["x"] = [pt[0] for pt in deduped]

        fgs_data[prefix]["y"] = [pt[1] for pt in deduped]

    return fgs_data


def _extract_p_params(
    raw_lines: list[str], event_idx: int = 1, warnings: list[str] | None = None
) -> dict | None:
    for raw_line in raw_lines:
        clean = raw_line.split("#", 1)[0].strip()
        tokens = clean.split()
        if tokens and tokens[0].lower() == "p":
            return parse_p_row(tokens[1:], event_idx=event_idx, warnings=warnings)
    return None


def _sanitize_event_ar_lines(
    event: dict, event_idx: int = 1, warnings: list[str] | None = None
) -> None:
    p_params = event.get("p_params") or P_DEFAULTS
    lag = p_params.get("ar_coeff_lag", 3)

    ar_alias_map = {
        "cY": ("cY", "Y", "cy", "y", "CY"),
        "cCb": ("cCb", "Cb", "ccb", "cb", "CCb", "CB"),
        "cCr": ("cCr", "Cr", "ccr", "cr", "CCr", "CR"),
    }

    for prefix in ("cY", "cCb", "cCr"):
        expected = _expected_ar_count(lag, prefix)
        aliases = ar_alias_map[prefix]

        matching_indices = []
        for idx, line in enumerate(event["raw_lines"]):
            clean = line.split("#", 1)[0].strip()
            tokens = clean.split()
            if tokens and tokens[0] in aliases:
                matching_indices.append((idx, tokens[0]))

        if not matching_indices:
            if expected > 0:
                new_line = f"\t{prefix} " + " ".join(["0"] * expected) + "\n"
                event["raw_lines"].append(new_line)
                if warnings is not None:
                    warnings.append(
                        f"Event {event_idx}: Missing line '{prefix}' for lag {lag}; generated {expected} zero-padded coefficients."
                    )
            else:
                new_line = f"\t{prefix}\n"
                event["raw_lines"].append(new_line)
                if warnings is not None:
                    warnings.append(
                        f"Event {event_idx}: Missing line '{prefix}' for lag {lag}; generated canonical empty coefficient line."
                    )
        else:
            selected_idx, matched_token = matching_indices[0]
            for idx, token in matching_indices:
                if token == prefix:
                    selected_idx, matched_token = idx, token
                    break

            if len(matching_indices) > 1:
                dup_indices = {idx for idx, _ in matching_indices if idx != selected_idx}
                event["raw_lines"] = [
                    line for i, line in enumerate(event["raw_lines"]) if i not in dup_indices
                ]
                for idx, line in enumerate(event["raw_lines"]):
                    clean = line.split("#", 1)[0].strip()
                    tokens = clean.split()
                    if tokens and tokens[0] in aliases:
                        selected_idx = idx
                        break
                if warnings is not None:
                    warnings.append(
                        f"Event {event_idx}: Multiple lines for AR channel '{prefix}' detected; preserved primary line and discarded redundant duplicate."
                    )

            if matched_token != prefix and warnings is not None:
                warnings.append(
                    f"Event {event_idx}: Legacy AR prefix '{matched_token}' normalized to canonical '{prefix}'."
                )

            coeffs = _extract_coeffs([event["raw_lines"][selected_idx]], prefix)
            clamped = [max(-128, min(127, c)) for c in coeffs]
            if clamped != coeffs and warnings is not None:
                warnings.append(
                    f"Event {event_idx}: Line '{prefix}' contained coefficients outside AFGS1 range [-128..127]; clamped to limits."
                )
            coeffs = clamped

            if expected == 0:
                event["raw_lines"][selected_idx] = f"\t{prefix}\n"
            elif len(coeffs) < expected:
                missing = expected - len(coeffs)
                coeffs.extend([0] * missing)
                event["raw_lines"][selected_idx] = (
                    f"\t{prefix} " + " ".join(str(c) for c in coeffs) + "\n"
                )
                if warnings is not None:
                    warnings.append(
                        f"Event {event_idx}: Line '{prefix}' had only {len(coeffs) - missing} coefficients (expected {expected} for lag {lag}; added {missing} trailing zeros."
                    )
            elif len(coeffs) > expected:
                orig_len = len(coeffs)
                coeffs = coeffs[:expected]
                event["raw_lines"][selected_idx] = (
                    f"\t{prefix} " + " ".join(str(c) for c in coeffs) + "\n"
                )
                if warnings is not None:
                    warnings.append(
                        f"Event {event_idx}: Line '{prefix}' had {orig_len} coefficients (expected {expected}); truncated excess."
                    )
            else:
                event["raw_lines"][selected_idx] = (
                    f"\t{prefix} " + " ".join(str(c) for c in coeffs) + "\n"
                )


def parse_fgs_events(
    content: str,
    return_warnings: bool = False,
    video_info: dict | None = None,
    max_duration_ticks: int | None = None,
):
    clean_content = content.lstrip("\ufeff")
    lines = [line.rstrip("\r\n") + "\n" for line in clean_content.splitlines()]

    filmgrn_idx = None
    version_tag = None
    warnings: list[str] = []

    for idx, line in enumerate(lines):
        clean = line.split("#", 1)[0].strip()
        stripped = clean.lower().replace(" ", "")
        if stripped in ("filmgrn1", "filmgrn", "afgs1") or (
            stripped.startswith("filmgrn") and stripped[7:].isdigit()
        ):
            filmgrn_idx = idx
            version_tag = "filmgrn1" if stripped in ("filmgrn1", "filmgrn", "afgs1") else stripped
            if clean != "filmgrn1":
                warnings.append(
                    f"Format identifier header '{clean}' normalized to canonical 'filmgrn1'."
                )
            break

    body_kw = {"p", "sy", "scb", "scr", "cy", "ccb", "ccr", "cb", "cr", "y", "e"}

    if filmgrn_idx is None:
        fgs_recognized = False
        first_body_idx = 0
        for idx, line in enumerate(lines):
            clean = line.split("#", 1)[0].strip()
            parts = clean.split()
            if parts and parts[0].lower() in body_kw:
                fgs_recognized = True
                first_body_idx = idx
                break

        if fgs_recognized:
            filmgrn_idx = first_body_idx
            version_tag = "filmgrn1"
            lines.insert(first_body_idx, "filmgrn1\n")
            warnings.append(
                "Missing 'filmgrn1' format identifier header; auto-synthesized standard AFGS1 header."
            )
        else:
            raise ValueError("Invalid FGS format: Missing 'filmgrn1' format identifier header.")

    if version_tag != "filmgrn1":
        raise ValueError(
            f"Unsupported FGS version '{version_tag}': this parser currently supports only 'filmgrn1' (AFGS1)."
        )

    events = []
    header_lines = list(lines[: filmgrn_idx + 1])
    current_event = None
    event_counter = 0

    def finalize_event(ev: dict, idx: int) -> None:
        has_child_payload = any(
            line.split("#", 1)[0].strip() for line in ev.get("raw_lines", [])
        )
        update_params = 1
        if len(ev.get("extra_params", [])) >= 3:
            try:
                update_params = int(ev["extra_params"][2])
            except (ValueError, TypeError):
                update_params = 1

        if update_params == 0 and not has_child_payload and events:
            prev_ev = events[-1]
            import copy

            ev["scale_data"] = copy.deepcopy(prev_ev.get("scale_data", {}))
            ev["p_params"] = copy.deepcopy(prev_ev.get("p_params", P_DEFAULTS))
            ev["raw_lines"] = list(prev_ev.get("raw_lines", []))
            if warnings is not None:
                warnings.append(
                    f"Event {idx}: 'update_parameters = 0' with omitted payload lines; inherited parameters from preceding event."
                )
        else:
            ev["scale_data"] = _parse_scale_from_lines(
                [line_text.strip() for line_text in ev["raw_lines"]],
                event_idx=idx,
                warnings=warnings,
            )
            ev["p_params"] = _extract_p_params(
                ev["raw_lines"], event_idx=idx, warnings=warnings
            )
            if ev["p_params"] is None:
                if update_params == 0 and events:
                    import copy

                    ev["p_params"] = copy.deepcopy(events[-1].get("p_params", P_DEFAULTS))
                else:
                    ev["p_params"] = dict(P_DEFAULTS)
                    warnings.append(
                        f"Event {idx}: Missing line 'p'; populated with AFGS1 standard defaults."
                    )

        chroma_from_luma = ev["p_params"].get("chroma_scaling_from_luma", 0) == 1
        if chroma_from_luma:
            if ev["scale_data"]["sCb"]["x"] or ev["scale_data"]["sCr"]["x"]:
                ev["scale_data"]["sCb"] = {"x": [], "y": []}
                ev["scale_data"]["sCr"] = {"x": [], "y": []}
                if warnings is not None:
                    warnings.append(
                        f"Event {idx}: 'chroma_scaling_from_luma' is enabled; cleared Chroma curves (must have 0 points per AFGS1 spec)."
                    )

        body_tokens_valid = {"p", "sy", "scb", "scr", "cy", "ccb", "ccr", "cb", "cr", "y", "e"}
        for line in ev["raw_lines"]:
            clean = line.split("#", 1)[0].strip()
            if not clean:
                continue
            token0 = clean.split()[0].lower()
            if token0 not in body_tokens_valid:
                if warnings is not None:
                    warnings.append(
                        f"Event {idx}: Non-standard inline content '{line.strip()}' detected in event body."
                    )

        _sanitize_event_ar_lines(ev, event_idx=idx, warnings=warnings)

        cy_coeffs, cb_coeffs, cr_coeffs = extract_ar_coeffs_from_raw_lines(ev["raw_lines"])
        lag = ev["p_params"].get("ar_coeff_lag", 3)

        p_tokens = p_params_to_tokens(ev["p_params"])
        canonical_raw = ["\tp " + " ".join(p_tokens) + "\n"]

        for ch in ("sY", "sCb", "sCr"):
            if chroma_from_luma and ch in ("sCb", "sCr"):
                canonical_raw.append(f"\t{ch} 0\n")
            else:
                data = ev["scale_data"].get(ch, {"x": [], "y": []})
                xs = data.get("x", [])
                ys = data.get("y", [])
                if len(xs) == 0:
                    canonical_raw.append(f"\t{ch} 0\n")
                else:
                    pairs = []
                    for x, y in zip(xs, ys):
                        pairs.extend([str(x), str(y)])
                    canonical_raw.append(f"\t{ch} {len(xs)} " + " ".join(pairs) + "\n")

        canonical_raw.append(format_c_line("cY", cy_coeffs, lag))
        canonical_raw.append(format_c_line("cCb", cb_coeffs, lag))
        canonical_raw.append(format_c_line("cCr", cr_coeffs, lag))

        ev["raw_lines"] = canonical_raw

        params_str = " ".join(ev.get("extra_params", ["1", "7391", "1"]))
        ev["e_line"] = f"E {ev['start_time']} {ev['end_time']} {params_str}\n"


    for line in lines[filmgrn_idx + 1 :]:
        clean = line.split("#", 1)[0].strip()
        tokens = clean.split()
        if not tokens:
            if current_event is not None:
                current_event["raw_lines"].append(line)
            continue

        token0_norm = tokens[0].lower().replace(" ", "")
        if token0_norm in ("filmgrn1", "filmgrn", "afgs1") or (
            token0_norm.startswith("filmgrn") and token0_norm[7:].isdigit()
        ):
            warnings.append(
                f"Duplicate format identifier '{tokens[0]}' detected in body; duplicate removed."
            )
            continue

        if tokens[0].upper() == "E":
            if tokens[0] != "E" and warnings is not None:
                warnings.append(
                    f"Event {event_counter + 1}: Line 'E' prefix '{tokens[0]}' normalized to uppercase 'E'."
                )
            event_counter += 1
            if current_event is not None:
                finalize_event(current_event, event_counter - 1)
                events.append(current_event)

            try:
                start_t = int(tokens[1]) if len(tokens) > 1 else 0
                end_t = int(tokens[2]) if len(tokens) > 2 else start_t + 10000000
            except ValueError:
                start_t, end_t = 0, 10000000

            if start_t < 0:
                warnings.append(
                    f"Event {event_counter}: Negative start timestamp {start_t} clamped to 0."
                )
                start_t = 0

            if end_t >= 10**15:
                clamped_end = 62_500_000_000
                warnings.append(
                    f"Event {event_counter}: Extreme timestamp {end_t} (UINT64_MAX dummy) clamped to timeline bounds."
                )
                end_t = clamped_end
            elif end_t <= start_t:
                clamped_end = start_t + 10_000_000
                warnings.append(
                    f"Event {event_counter}: End timestamp {end_t} <= start timestamp {start_t}; adjusted end to {clamped_end}."
                )
                end_t = clamped_end

            extra_params = tokens[3:]
            if len(extra_params) < 3:
                defaults = ["1", "7391", "1"]
                extra_params.extend(defaults[len(extra_params) : 3])
                warnings.append(
                    f"Event {event_counter} ({start_t}-{end_t}): Missing parameters on 'E' line; populated with defaults [apply=1, seed=7391, update=1]."
                )
            elif len(extra_params) > 3:
                warnings.append(
                    f"Event {event_counter} ({start_t}-{end_t}): Line 'E' had excess parameters; truncated to 3 [apply_grain, random_seed, update_parameters]."
                )
                extra_params = extra_params[:3]

            try:
                raw_ag = int(extra_params[0])
                clamped_ag = 1 if raw_ag != 0 else 0

                if clamped_ag != raw_ag and warnings is not None:
                    warnings.append(
                        f"Event {event_counter}: Parameter 'apply_grain' ({raw_ag}) invalid; normalized to {clamped_ag}."
                    )
                extra_params[0] = str(clamped_ag)
            except ValueError:
                if warnings is not None:
                    warnings.append(
                        f"Event {event_counter}: Non-integer token '{extra_params[0]}' for 'apply_grain'; defaulted to 1."
                    )
                extra_params[0] = "1"

            try:
                raw_seed = int(extra_params[1])
                clamped_seed = max(0, min(65535, raw_seed))
                if clamped_seed != raw_seed and warnings is not None:
                    warnings.append(
                        f"Event {event_counter}: Parameter 'random_seed' ({raw_seed}) out of 16-bit range [0..65535]; clamped to {clamped_seed}."
                    )
                extra_params[1] = str(clamped_seed)
            except ValueError:
                if warnings is not None:
                    warnings.append(
                        f"Event {event_counter}: Non-integer token '{extra_params[1]}' for 'random_seed'; defaulted to 7391."
                    )
                extra_params[1] = "7391"

            try:
                raw_up = int(extra_params[2])
                clamped_up = 1 if raw_up != 0 else 0
                if event_counter == 1 and clamped_up == 0:
                    clamped_up = 1
                    if warnings is not None:
                        warnings.append(
                            "Event 1: Parameter 'update_parameters' set to 0 on initial event; normalized to 1."
                        )
                elif clamped_up != raw_up and warnings is not None:
                    warnings.append(
                        f"Event {event_counter}: Parameter 'update_parameters' ({raw_up}) invalid; normalized to {clamped_up}."
                    )
                extra_params[2] = str(clamped_up)
            except ValueError:
                if warnings is not None:
                    warnings.append(
                        f"Event {event_counter}: Non-integer token '{extra_params[2]}' for 'update_parameters'; defaulted to 1."
                    )
                extra_params[2] = "1"

            current_event = {
                "start_time": start_t,
                "end_time": end_t,
                "e_line": line,
                "extra_params": extra_params,
                "raw_lines": [],
                "scale_data": None,
                "p_params": None,
            }
        elif current_event is not None:
            current_event["raw_lines"].append(line)
        else:
            header_lines.append(line)

    max_ticks = None
    if max_duration_ticks is not None and max_duration_ticks > 0:
        max_ticks = max_duration_ticks
    elif video_info:
        v_obj = video_info
        if isinstance(video_info, str):
            from fgseditor_qt.tools.video_probe import probe_video
            try:
                v_obj = probe_video(video_info)
            except Exception:
                v_obj = None
        if v_obj:
            from fgseditor_qt.math.time_utils import video_info_to_ticks

            vt = video_info_to_ticks(v_obj)
            if vt > 0:
                max_ticks = vt

    if current_event is not None:
        finalize_event(current_event, event_counter)
        events.append(current_event)
    elif not events:
        fgs_prefixes = {"p", "sy", "scb", "scr", "cy", "ccb", "ccr", "cb", "cr", "y"}
        body_lines = []

        actual_headers = []
        for line in header_lines:
            clean = line.split("#", 1)[0].strip()
            tokens = clean.split()
            if tokens and tokens[0].lower() in fgs_prefixes:
                body_lines.append(line)
            else:
                actual_headers.append(line)

        if body_lines:
            ev_end = max_ticks if (max_ticks and max_ticks > 0) else 10000000
            warnings.append(
                f"Event 1: Missing 'E' event line in static FGS; generated default event [0..{ev_end}, seed=7391]."
            )
            ev = {
                "start_time": 0,
                "end_time": ev_end,
                "e_line": f"E 0 {ev_end} 1 7391 1\n",
                "extra_params": ["1", "7391", "1"],
                "raw_lines": body_lines,
                "scale_data": None,
                "p_params": None,
            }
            finalize_event(ev, 1)
            events.append(ev)
            header_lines = actual_headers

    if len(events) > 1 and warnings is not None:
        for i in range(len(events) - 1):
            curr_end = events[i].get("end_time", 0)
            next_start = events[i + 1].get("start_time", 0)
            if next_start < curr_end:
                warnings.append(
                    f"Overlapping event boundary between Event {i + 1} (end: {curr_end}) and Event {i + 2} (start: {next_start})."
                )

    if max_ticks and max_ticks > 0 and events:
        dropped = [ev for ev in events if ev.get("start_time", 0) >= max_ticks]
        if dropped:
            events = [ev for ev in events if ev.get("start_time", 0) < max_ticks]
            if warnings is not None:
                warnings.append(
                    f"Trimmed {len(dropped)} event(s) starting beyond video duration ({max_ticks} ticks)."
                )

        if not events and dropped:
            ev = dropped[0]
            ev["start_time"] = 0
            ev["end_time"] = max_ticks
            params_str = " ".join(ev.get("extra_params", ["1", "7391", "1"]))
            ev["e_line"] = f"E {ev['start_time']} {ev['end_time']} {params_str}\n"
            events = [ev]
            if warnings is not None:
                warnings.append(
                    f"All events started beyond video duration ({max_ticks} ticks); clamped first event to [0..{max_ticks}]."
                )

        for ev in events:
            if ev.get("end_time", 0) > max_ticks:
                old_end = ev["end_time"]
                ev["end_time"] = max_ticks
                params_str = " ".join(ev.get("extra_params", ["1", "7391", "1"]))
                ev["e_line"] = f"E {ev['start_time']} {ev['end_time']} {params_str}\n"
                if warnings is not None:
                    warnings.append(
                        f"Trimmed event end timestamp from {old_end} to video duration ({max_ticks} ticks)."
                    )

    if return_warnings:
        return header_lines, events, warnings
    return header_lines, events


def parse_fgs_with_report(
    content: str,
    video_info: dict | None = None,
    max_duration_ticks: int | None = None,
) -> tuple[list[str], list[dict], list[str]]:
    return parse_fgs_events(
        content,
        return_warnings=True,
        video_info=video_info,
        max_duration_ticks=max_duration_ticks,
    )


def sanitize_fgs_text(
    content: str,
    video_info: dict | None = None,
    max_duration_ticks: int | None = None,
) -> tuple[str, list[str]]:
    from fgseditor_qt.core.fgs_save import build_dynamic_lines

    header_lines, events, warnings = parse_fgs_events(
        content,
        return_warnings=True,
        video_info=video_info,
        max_duration_ticks=max_duration_ticks,
    )
    lines = build_dynamic_lines(header_lines, events)
    return "".join(lines), warnings


def is_dynamic(events):
    return len(events) > 1


def available_grain_presets() -> list[str]:
    import os
    from fgseditor_qt.core.app_paths import get_base_dir

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
    from fgseditor_qt.core.app_paths import get_base_dir

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
        "p_tokens": p_params_to_tokens(p_dict) if p_dict else [],
        "cY": cy,
        "cCb": cb,
        "cCr": cr,
    }

