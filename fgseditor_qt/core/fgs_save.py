from __future__ import annotations
import os
from PySide6.QtWidgets import QFileDialog, QMessageBox
from fgseditor_qt.core import fgs_parser
from fgseditor_qt.core.settings_manager import get_dialog_dir, update_dialog_dir


def _build_scale_line(prefix: str, data: dict, chroma_from_luma: bool = False) -> str:
    max_pts = 14 if prefix == "sY" else 10

    if chroma_from_luma and prefix in ("sCb", "sCr"):
        return f"\t{prefix} 0\n"

    raw_x = data.get("x", [])
    raw_y = data.get("y", [])

    pairs = []
    seen_x = set()
    for x, y in sorted(zip(raw_x, raw_y), key=lambda pt: pt[0]):
        cx = max(0, min(255, int(x)))
        cy = max(0, min(255, int(y)))
        if cx not in seen_x:
            seen_x.add(cx)
            pairs.append((cx, cy))

    if len(pairs) > max_pts:
        pairs = pairs[:max_pts]


    pts = len(pairs)
    if pts == 0:
        return f"\t{prefix} 0\n"
    if pts == 1:
        cx, cy = pairs[0]
        if cx > 150:
            new_x = max(0, cx - 1)
            pairs = [(new_x, cy), (cx, cy)]
        else:
            new_x = min(255, cx + 1)
            pairs = [(cx, cy), (new_x, cy)]
        pts = 2

    flat_pairs = []
    for x, y in pairs:
        flat_pairs.extend([str(x), str(y)])

    return f"\t{prefix} {pts} " + " ".join(flat_pairs) + "\n"


def _build_p_line(p_params: dict) -> str:
    from fgseditor_qt.core.fgs_parser import p_params_to_tokens

    tokens = p_params_to_tokens(p_params)
    return "\tp " + " ".join(tokens) + "\n"


_build_c_line = fgs_parser.format_c_line


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

    cy_coeffs, cb_coeffs, cr_coeffs = fgs_parser.extract_ar_coeffs_from_raw_lines(
        original_lines
    )

    e_line_tokens = None

    for line in original_lines:
        clean = line.split("#", 1)[0].strip()
        tokens = clean.split()
        first_token = tokens[0] if tokens else ""

        if first_token.upper() == "E" and e_line_tokens is None:
            e_line_tokens = tokens

    has_e = e_line_tokens is not None
    if not has_e and (start_time is None or end_time is None):
        raise ValueError(
            "Missing E line in original FGS and no start/end times provided."
        )

    result = ["filmgrn1\n"]

    if start_time is not None and end_time is not None:
        st, et = start_time, end_time
    elif e_line_tokens is not None:
        try:
            st = int(e_line_tokens[1]) if len(e_line_tokens) > 1 else 0
            et = int(e_line_tokens[2]) if len(e_line_tokens) > 2 else st + 10000000
        except ValueError:
            st, et = 0, 10000000
    else:
        st, et = 0, 10000000

    apply_g = "1"
    seed_v = str(grain_seed) if grain_seed is not None else "7391"
    update_p = "1"

    if e_line_tokens is not None:
        if len(e_line_tokens) > 3:
            apply_g = e_line_tokens[3]
        if len(e_line_tokens) > 4 and grain_seed is None:
            seed_v = e_line_tokens[4]
        if len(e_line_tokens) > 5:
            update_p = e_line_tokens[5]

    result.append(f"E {st} {et} {apply_g} {seed_v} {update_p}\n")

    result.append(_build_p_line(p_params))

    chroma_from_luma = p_params.get("chroma_scaling_from_luma", 0) == 1
    for ch_prefix in ("sY", "sCb", "sCr"):
        data = scale_data.get(ch_prefix, {"x": [], "y": []})
        result.append(_build_scale_line(ch_prefix, data, chroma_from_luma=chroma_from_luma))

    result.append(fgs_parser.format_c_line("cY", cy_coeffs, lag))
    result.append(fgs_parser.format_c_line("cCb", cb_coeffs, lag))
    result.append(fgs_parser.format_c_line("cCr", cr_coeffs, lag))

    return result


def build_dynamic_lines(
    header_lines: list[str],
    events: list[dict],
) -> list[str]:
    lines: list[str] = ["filmgrn1\n"]

    for ev in events:
        st = ev.get("start_time", 0)
        et = ev.get("end_time", st + 10000000)
        extra = list(ev.get("extra_params") or ["1", "7391", "1"])

        if len(extra) < 3:
            defaults = ["1", "7391", "1"]
            extra.extend(defaults[len(extra) : 3])
        elif len(extra) > 3:
            extra = extra[:3]

        lines.append(f"E {st} {et} {' '.join(extra)}\n")

        scale_data = fgs_parser.get_scale_data(ev)
        p_params = fgs_parser.get_p_params(ev)
        lag = p_params.get("ar_coeff_lag", 3)

        cy_coeffs, cb_coeffs, cr_coeffs = fgs_parser.extract_ar_coeffs_from_raw_lines(
            ev.get("raw_lines", [])
        )

        lines.append(_build_p_line(p_params))

        chroma_from_luma = p_params.get("chroma_scaling_from_luma", 0) == 1
        for ch_prefix in ("sY", "sCb", "sCr"):
            data = scale_data.get(ch_prefix, {"x": [], "y": []})
            lines.append(_build_scale_line(ch_prefix, data, chroma_from_luma=chroma_from_luma))

        lines.append(fgs_parser.format_c_line("cY", cy_coeffs, lag))
        lines.append(fgs_parser.format_c_line("cCb", cb_coeffs, lag))
        lines.append(fgs_parser.format_c_line("cCr", cr_coeffs, lag))

    return lines


def save_dynamic_fgs(
    parent_widget,
    original_filepath: str | None,
    header_lines: list[str],
    events: list[dict],
    default_name: str = "modified_fgs.txt",
    force_path: str | None = None,
) -> str | None:
    has_chroma_luma = any(
        fgs_parser.get_p_params(ev).get("chroma_scaling_from_luma", 0) == 1
        for ev in events
    )
    if has_chroma_luma:
        reply = QMessageBox.warning(
            parent_widget,
            "x265 Compatibility Warning",
            "'Chroma Scaling from Luma' is enabled.\n\n"
            "x265 does not support this feature and will ignore Chroma grain.\n\n"
            "Save anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.No:
            return None

    if force_path:
        save_path = force_path
    else:
        default_out = (
            original_filepath
            if original_filepath
            else os.path.join(get_dialog_dir("last_fgs_dir"), default_name)
        )
        save_path, _ = QFileDialog.getSaveFileName(
            parent_widget, "Save Dynamic FGS", default_out, "Film Grain Tables (*.tbl *.txt);;All Files (*)"
        )

    if not save_path:
        return None

    temp_save_path = save_path + ".tmp"
    try:
        new_lines = build_dynamic_lines(header_lines, events)
        with open(temp_save_path, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(new_lines)
        os.replace(temp_save_path, save_path)
        update_dialog_dir("last_fgs_dir", save_path)
        return save_path
    except Exception as e:
        QMessageBox.critical(
            parent_widget, "Save Error", f"Could not save Dynamic FGS:\n{str(e)}"
        )
        return None
    finally:
        if os.path.isfile(temp_save_path):
            try:
                os.remove(temp_save_path)
            except OSError:
                pass


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
) -> str | None:
    if p_params and p_params.get("chroma_scaling_from_luma", 0) == 1:
        reply = QMessageBox.warning(
            parent_widget,
            "x265 Compatibility Warning",
            "'Chroma Scaling from Luma' is enabled.\n\n"
            "x265 does not support this feature and will ignore Chroma grain.\n\n"
            "Save anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.No:
            return None

    if force_path:
        save_path = force_path
    else:
        default_out = (
            original_filepath
            if original_filepath
            else os.path.join(get_dialog_dir("last_fgs_dir"), default_name)
        )
        save_path, _ = QFileDialog.getSaveFileName(
            parent_widget, "Save Static FGS", default_out, "Film Grain Tables (*.tbl *.txt);;All Files (*)"
        )

    if not save_path:
        return None

    temp_save_path = save_path + ".tmp"
    try:
        final_original = []
        if original_filepath and os.path.exists(original_filepath):
            with open(original_filepath, "r", encoding="utf-8") as fh:
                file_lines = fh.readlines()

            found_e = False
            for line in file_lines:
                final_original.append(line)
                clean = line.split("#", 1)[0].strip()
                tokens = clean.split()
                if tokens and tokens[0].upper() == "E":
                    found_e = True
                    break
            if not found_e:
                headers_only = []
                fgs_keys = {"p", "sy", "scb", "scr", "cy", "ccb", "ccr", "cb", "cr", "y", "e"}
                for line in file_lines:
                    clean = line.split("#", 1)[0].strip()
                    tokens = clean.split()
                    if tokens and tokens[0].lower() in fgs_keys:
                        break
                    headers_only.append(line)
                final_original = headers_only

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

        with open(temp_save_path, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(new_lines)
        os.replace(temp_save_path, save_path)
        update_dialog_dir("last_fgs_dir", save_path)
        return save_path
    except Exception as e:
        QMessageBox.critical(
            parent_widget, "Save Error", f"Could not save Static FGS:\n{str(e)}"
        )
        return None
    finally:
        if os.path.isfile(temp_save_path):
            try:
                os.remove(temp_save_path)
            except OSError:
                pass
