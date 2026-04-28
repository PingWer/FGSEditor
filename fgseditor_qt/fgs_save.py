from __future__ import annotations
import os
from PySide6.QtWidgets import QFileDialog, QMessageBox
from . import fgs_parser
from .app_paths import get_base_dir


def _expected_coeff_count(ar_coeff_lag: int) -> int:
    return 2 * ar_coeff_lag * (ar_coeff_lag + 1)


def _count_cy_coeffs(raw_lines: list[str]) -> int:
    for line in raw_lines:
        tokens = line.strip().split()
        if tokens and tokens[0] == "cY":
            return len(tokens) - 1
    return 0


def _infer_ar_lag_from_coeffs(coeff_count: int) -> int:
    for lag in range(4):
        if _expected_coeff_count(lag) == coeff_count:
            return lag
    return 0


def _validate_and_adjust_ar_lag(
    p_params: dict | None, raw_lines: list[str]
) -> dict | None:
    if p_params is None:
        return None

    coeff_count = _count_cy_coeffs(raw_lines)
    current_lag = p_params.get("ar_coeff_lag", 3)
    expected_count = _expected_coeff_count(current_lag)

    if coeff_count != expected_count and coeff_count > 0:
        corrected_lag = _infer_ar_lag_from_coeffs(coeff_count)
        p_params = dict(p_params)
        p_params["ar_coeff_lag"] = corrected_lag
    elif coeff_count == 0:
        p_params = dict(p_params)
        p_params["ar_coeff_lag"] = 0

    return p_params


def _build_scale_line(prefix: str, data: dict) -> str:
    pts = len(data.get("x", []))
    if pts == 0:
        return f"  {prefix} 0\n"
    pairs = []
    for x, y in zip(data["x"], data["y"]):
        pairs.extend([str(x), str(y)])
    return f"  {prefix} {pts} " + " ".join(pairs) + "\n"


def _build_p_line(p_params: dict | None, original_line: str) -> str:
    if p_params is None:
        return original_line
    from .fgs_parser import p_params_to_tokens

    tokens = p_params_to_tokens(p_params)
    return "p " + " ".join(tokens) + "\n"


def _build_c_line(prefix: str, tokens: list[str], p_params: dict | None) -> str:
    if p_params is None:
        return "\t" + " ".join(tokens) + "\n"

    lag = p_params.get("ar_coeff_lag", 0)
    expected_count = _expected_coeff_count(lag)
    if prefix in ("cCb", "cCr"):
        expected_count += 1

    if expected_count == 0:
        return f"\t{prefix} 0\n"

    coeffs = tokens[1:]

    if len(coeffs) == 1 and coeffs[0] == "0":
        coeffs = []

    if len(coeffs) < expected_count:
        coeffs.extend(["0"] * (expected_count - len(coeffs)))
    elif len(coeffs) > expected_count:
        coeffs = coeffs[:expected_count]

    return f"\t{prefix} " + " ".join(coeffs) + "\n"


def build_static_lines(
    original_lines: list[str],
    scale_data: dict,
    p_params: dict | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
) -> list[str]:

    raw_data_lines = []
    for line in original_lines:
        tokens = line.strip().split()
        if tokens and tokens[0] in ("cY", "cCb", "cCr", "p", "sY", "sCb", "sCr"):
            raw_data_lines.append(line)

    p_params = _validate_and_adjust_ar_lag(p_params, raw_data_lines)

    result = []
    for line in original_lines:
        tokens = line.strip().split()
        if not tokens:
            result.append(line)
            continue
        prefix = tokens[0]
        if prefix in ("sY", "sCb", "sCr"):
            result.append(
                _build_scale_line(prefix, scale_data.get(prefix, {"x": [], "y": []}))
            )
        elif prefix == "p" and p_params is not None:
            result.append(_build_p_line(p_params, line))
        elif prefix == "E" and start_time is not None and end_time is not None:
            rest = tokens[3:]
            result.append(f"E {start_time} {end_time} " + " ".join(rest) + "\n")
        elif prefix in ("cY", "cCb", "cCr"):
            result.append(_build_c_line(prefix, tokens, p_params))
        else:
            result.append(line)
    return result


def build_dynamic_lines(
    header_lines: list[str],
    events: list[dict],
) -> list[str]:

    lines: list[str] = list(header_lines)

    for ev in events:
        params_str = " ".join(ev["extra_params"])
        lines.append(f"E {ev['start_time']} {ev['end_time']} {params_str}\n")

        scale_data = fgs_parser.get_scale_data(ev)
        p_params = fgs_parser.get_p_params(ev)

        p_params = _validate_and_adjust_ar_lag(p_params, ev.get("raw_lines", []))

        for raw_line in ev["raw_lines"]:
            tokens = raw_line.strip().split()
            if not tokens:
                lines.append(raw_line)
                continue
            prefix = tokens[0]
            if prefix in ("sY", "sCb", "sCr"):
                lines.append(
                    _build_scale_line(
                        prefix, scale_data.get(prefix, {"x": [], "y": []})
                    )
                )
            elif prefix == "p" and p_params is not None:
                lines.append(_build_p_line(p_params, raw_line))
            elif prefix in ("cY", "cCb", "cCr"):
                lines.append(_build_c_line(prefix, tokens, p_params))
            else:
                lines.append(raw_line)

    return lines


def save_fgs(
    parent_widget,
    header_lines: list[str],
    events: list[dict],
    default_name: str = "modified_fgs.txt",
) -> bool:
    default_path = os.path.join(get_base_dir(), default_name)
    save_path, _ = QFileDialog.getSaveFileName(
        parent_widget, "Save FGS File", default_path, "Text Files (*.txt)"
    )
    if not save_path:
        return False

    lines = build_dynamic_lines(header_lines, events)

    with open(save_path, "w", encoding="utf-8") as fh:
        fh.writelines(lines)

    QMessageBox.information(parent_widget, "Saved", f"File saved to:\n{save_path}")
    return True


def save_dynamic_fgs(
    parent_widget,
    original_filepath: str,
    header_lines: list[str],
    events: list[dict],
    default_name: str = "modified_fgs.txt",
) -> bool:
    return save_fgs(
        parent_widget,
        header_lines=header_lines,
        events=events,
        default_name=os.path.basename(original_filepath)
        if original_filepath
        else default_name,
    )


def save_static_fgs(
    parent_widget,
    original_filepath: str,
    scale_data: dict,
    p_params: dict | None = None,
    event_raw_lines: list[str] | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
    default_name: str = "modified_fgs.txt",
) -> bool:
    default_path = os.path.join(get_base_dir(), default_name)
    save_path, _ = QFileDialog.getSaveFileName(
        parent_widget, "Save Modified FGS", default_path, "Text Files (*.txt)"
    )
    if not save_path:
        return False

    with open(original_filepath, "r", encoding="utf-8") as fh:
        original_lines = fh.readlines()

    if event_raw_lines is not None:
        header_and_e = []
        for line in original_lines:
            header_and_e.append(line)
            tokens = line.strip().split()
            if tokens and tokens[0] == "E":
                break
        original_lines = header_and_e + event_raw_lines

    new_lines = build_static_lines(
        original_lines,
        scale_data,
        p_params,
        start_time=start_time,
        end_time=end_time,
    )

    with open(save_path, "w", encoding="utf-8") as fh:
        fh.writelines(new_lines)

    QMessageBox.information(parent_widget, "Saved", f"File saved to:\n{save_path}")
    return True
