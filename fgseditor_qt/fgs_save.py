from __future__ import annotations
import os
from PySide6.QtWidgets import QFileDialog, QMessageBox
from .app_paths import get_base_dir


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
    from .fgs_math import p_params_to_tokens

    tokens = p_params_to_tokens(p_params)
    return "  p " + " ".join(tokens) + "\n"


def build_static_lines(
    original_lines: list[str],
    scale_data: dict,
    p_params: dict | None = None,
    grain_size: int = 1,
    autobalance: bool = False,
) -> list[str]:

    if autobalance:
        from .fgs_math import (
            apply_autobalance_to_scale_data,
            extract_ar_coeffs_from_raw_lines,
        )

        cy, cb, cr = extract_ar_coeffs_from_raw_lines(original_lines)
        ar_shift = p_params.get("ar_coeff_shift", 8) if p_params else 8
        scale_data = apply_autobalance_to_scale_data(
            scale_data, grain_size, {"cY": cy, "cCb": cb, "cCr": cr}, ar_shift
        )

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
        else:
            result.append(line)
    return result


def build_dynamic_lines(
    header_lines: list[str],
    events: list[dict],
    autobalance: bool = False,
) -> list[str]:

    lines: list[str] = list(header_lines)

    for ev in events:
        params_str = " ".join(ev["extra_params"])
        lines.append(f"E {ev['start_time']} {ev['end_time']} {params_str}\n")

        scale_data = ev["scale_data"]
        p_params = ev.get("p_params")

        if autobalance:
            from .fgs_math import (
                apply_autobalance_to_scale_data,
                extract_ar_coeffs_from_raw_lines,
            )

            gs = ev.get(
                "grain_size", (p_params.get("grain_size", 1) if p_params else 1)
            )
            cy, cb, cr = extract_ar_coeffs_from_raw_lines(ev.get("raw_lines", []))
            ar_shift = p_params.get("ar_coeff_shift", 8) if p_params else 8
            scale_data = apply_autobalance_to_scale_data(
                scale_data, gs, {"cY": cy, "cCb": cb, "cCr": cr}, ar_shift
            )

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
            else:
                lines.append(raw_line)

    return lines


def save_fgs(
    parent_widget,
    header_lines: list[str],
    events: list[dict],
    autobalance: bool = False,
    default_name: str = "modified_fgs.txt",
) -> bool:
    default_path = os.path.join(get_base_dir(), default_name)
    save_path, _ = QFileDialog.getSaveFileName(
        parent_widget, "Save FGS File", default_path, "Text Files (*.txt)"
    )
    if not save_path:
        return False

    lines = build_dynamic_lines(header_lines, events, autobalance=autobalance)

    with open(save_path, "w", encoding="utf-8") as fh:
        fh.writelines(lines)

    QMessageBox.information(parent_widget, "Saved", f"File saved to:\n{save_path}")
    return True


def save_dynamic_fgs(
    parent_widget,
    original_filepath: str,
    header_lines: list[str],
    events: list[dict],
    autobalance: bool = False,
    default_name: str = "modified_fgs.txt",
) -> bool:
    return save_fgs(
        parent_widget,
        header_lines=header_lines,
        events=events,
        autobalance=autobalance,
        default_name=os.path.basename(original_filepath)
        if original_filepath
        else default_name,
    )


def save_static_fgs(
    parent_widget,
    original_filepath: str,
    scale_data: dict,
    p_params: dict | None = None,
    grain_size: int = 1,
    autobalance: bool = False,
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

    new_lines = build_static_lines(
        original_lines,
        scale_data,
        p_params,
        grain_size=grain_size,
        autobalance=autobalance,
    )

    with open(save_path, "w", encoding="utf-8") as fh:
        fh.writelines(new_lines)

    QMessageBox.information(parent_widget, "Saved", f"File saved to:\n{save_path}")
    return True
