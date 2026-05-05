from __future__ import annotations
import os
from PySide6.QtWidgets import QFileDialog, QMessageBox
from . import fgs_parser
from .app_paths import get_base_dir


def _expected_coeff_count(ar_coeff_lag: int) -> int:
    return 2 * ar_coeff_lag * (ar_coeff_lag + 1)


def _build_scale_line(prefix: str, data: dict) -> str:
    pts = len(data.get("x", []))
    if pts == 0:
        return f"  {prefix} 0\n"
    pairs = []
    for x, y in zip(data["x"], data["y"]):
        pairs.extend([str(x), str(y)])
    return f"  {prefix} {pts} " + " ".join(pairs) + "\n"


def _build_p_line(p_params: dict) -> str:
    from .fgs_parser import p_params_to_tokens

    tokens = p_params_to_tokens(p_params)
    return "p " + " ".join(tokens) + "\n"


def _build_c_line(prefix: str, coeffs: list[int], lag: int) -> str:
    expected_count = _expected_coeff_count(lag)
    if prefix in ("cCb", "cCr"):
        expected_count += 1

    if expected_count == 0:
        return f"  {prefix}\n"

    str_coeffs = [str(c) for c in coeffs]

    if len(str_coeffs) == 1 and str_coeffs[0] == "0":
        str_coeffs = ["0"] * expected_count
    elif len(str_coeffs) < expected_count:
        str_coeffs.extend(["0"] * (expected_count - len(str_coeffs)))
    elif len(str_coeffs) > expected_count:
        str_coeffs = str_coeffs[:expected_count]

    if not str_coeffs:
        str_coeffs = ["0"] * expected_count

    return f"  {prefix} " + " ".join(str_coeffs) + "\n"


def build_static_lines(
    original_lines: list[str],
    scale_data: dict,
    p_params: dict | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
    grain_seed: int | None = None,
) -> list[str]:
    if p_params is None:
        p_params = dict(fgs_parser.P_DEFAULTS)

    lag = p_params.get("ar_coeff_lag", 3)

    # Extract existing coeffs from original lines
    cy_coeffs, cb_coeffs, cr_coeffs = fgs_parser.extract_ar_coeffs_from_raw_lines(
        original_lines
    )

    result = []

    has_header = any(line.strip() == "filmgrn1" for line in original_lines)
    if not has_header:
        result.append("filmgrn1\n")
    has_e = any(line.strip().startswith("E ") for line in original_lines)
    if not has_e and (start_time is None or end_time is None):
        raise ValueError(
            "Missing E line in original FGS and no start/end times provided."
        )

    for line in original_lines:
        tokens = line.strip().split()
        if not tokens:
            result.append(line)
            continue

        prefix = tokens[0]
        if prefix in ("sY", "sCb", "sCr", "cY", "cCb", "cCr", "p"):
            continue

        if prefix == "E":
            if start_time is not None and end_time is not None:
                if len(tokens) > 4 and grain_seed is not None:
                    tokens[4] = str(grain_seed)
                elif len(tokens) <= 4 and grain_seed is not None:
                    # If E line was too short, pad it
                    while len(tokens) < 4:
                        tokens.append("1")
                    tokens.append(str(grain_seed))
                    if len(tokens) < 6:
                        tokens.append("1")

                rest = (
                    tokens[3:]
                    if len(tokens) > 3
                    else ["1", str(grain_seed or 7391), "1"]
                )
                result.append(f"E {start_time} {end_time} " + " ".join(rest) + "\n")
            else:
                result.append(line)
        else:
            result.append(line)

    if not has_e and start_time is not None and end_time is not None:
        seed_val = grain_seed if grain_seed is not None else 7391
        result.append(f"E {start_time} {end_time} 1 {seed_val} 1\n")
    result.append(_build_p_line(p_params))

    for ch_prefix in ("sY", "sCb", "sCr"):
        result.append(
            _build_scale_line(ch_prefix, scale_data.get(ch_prefix, {"x": [], "y": []}))
        )

    result.append(_build_c_line("cY", cy_coeffs, lag))
    result.append(_build_c_line("cCb", cb_coeffs, lag))
    result.append(_build_c_line("cCr", cr_coeffs, lag))

    return result


def build_dynamic_lines(
    header_lines: list[str],
    events: list[dict],
) -> list[str]:

    lines: list[str] = list(header_lines)

    for ev in events:
        params_str = " ".join(ev.get("extra_params", ["1", "6967", "1"]))
        lines.append(f"E {ev['start_time']} {ev['end_time']} {params_str}\n")

        scale_data = fgs_parser.get_scale_data(ev)
        p_params = fgs_parser.get_p_params(ev)
        lag = p_params.get("ar_coeff_lag", 3)

        cy_coeffs, cb_coeffs, cr_coeffs = fgs_parser.extract_ar_coeffs_from_raw_lines(
            ev.get("raw_lines", [])
        )

        # We keep lines that are not part of our systematic generation
        for raw_line in ev.get("raw_lines", []):
            tokens = raw_line.strip().split()
            if not tokens:
                lines.append(raw_line)
                continue
            prefix = tokens[0]
            if prefix not in ("sY", "sCb", "sCr", "cY", "cCb", "cCr", "p"):
                lines.append(raw_line)

        lines.append(_build_p_line(p_params))

        for ch_prefix in ("sY", "sCb", "sCr"):
            lines.append(
                _build_scale_line(
                    ch_prefix, scale_data.get(ch_prefix, {"x": [], "y": []})
                )
            )

        lines.append(_build_c_line("cY", cy_coeffs, lag))
        lines.append(_build_c_line("cCb", cb_coeffs, lag))
        lines.append(_build_c_line("cCr", cr_coeffs, lag))

    return lines


def save_dynamic_fgs(
    parent_widget,
    original_filepath: str | None,
    header_lines: list[str],
    events: list[dict],
    default_name: str = "modified_fgs.txt",
    force_path: str | None = None,
) -> bool:
    if force_path:
        save_path = force_path
    else:
        default_out = (
            original_filepath
            if original_filepath
            else os.path.join(get_base_dir(), default_name)
        )
        save_path, _ = QFileDialog.getSaveFileName(
            parent_widget, "Save Dynamic FGS", default_out, "Text Files (*.txt)"
        )

    if not save_path:
        return False

    try:
        new_lines = build_dynamic_lines(header_lines, events)
        with open(save_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return True
    except Exception as e:
        QMessageBox.critical(
            parent_widget, "Save Error", f"Could not save Dynamic FGS:\n{str(e)}"
        )
        return False


def save_static_fgs(
    parent_widget,
    original_filepath: str | None,
    scale_data: dict,
    p_params: dict | None = None,
    event_raw_lines: list[str] | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
    grain_seed: int | None = None,
    default_name: str = "modified_fgs.txt",
    force_path: str | None = None,
) -> bool:
    if force_path:
        save_path = force_path
    else:
        default_out = (
            original_filepath
            if original_filepath
            else os.path.join(get_base_dir(), default_name)
        )
        save_path, _ = QFileDialog.getSaveFileName(
            parent_widget, "Save Static FGS", default_out, "Text Files (*.txt)"
        )

    if not save_path:
        return False

    try:
        # Load header and E from existing file if we are modifying
        final_original = []
        if original_filepath and os.path.exists(original_filepath):
            with open(original_filepath, "r", encoding="utf-8") as fh:
                file_lines = fh.readlines()

            # Extract up to E
            for line in file_lines:
                final_original.append(line)
                if line.strip().startswith("E "):
                    break

        if event_raw_lines:
            final_original.extend(event_raw_lines)

        new_lines = build_static_lines(
            final_original,
            scale_data,
            p_params,
            start_time=start_time,
            end_time=end_time,
            grain_seed=grain_seed,
        )

        with open(save_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return True
    except Exception as e:
        QMessageBox.critical(
            parent_widget, "Save Error", f"Could not save Static FGS:\n{str(e)}"
        )
        return False
