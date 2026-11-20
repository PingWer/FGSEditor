from __future__ import annotations
import copy
import math
import os
import subprocess
import sys
from typing import Sequence, Callable
import numpy as np


from fgseditor_qt.core import fgs_parser
from fgseditor_qt.math import fgs_grain_sim


LAG3_OFFSETS = fgs_grain_sim._build_ar_offsets(3)
LAG2_OFFSETS = fgs_grain_sim._build_ar_offsets(2)
LAG1_OFFSETS = fgs_grain_sim._build_ar_offsets(1)

LAG3_INDEX_MAP = {p: i for i, p in enumerate(LAG3_OFFSETS)}
LAG2_INDEX_MAP = {p: i for i, p in enumerate(LAG2_OFFSETS)}
LAG2_TO_LAG3 = np.array([LAG3_INDEX_MAP[p] for p in LAG2_OFFSETS], dtype=np.int32)
LAG1_TO_LAG3 = np.array([LAG3_INDEX_MAP[p] for p in LAG1_OFFSETS], dtype=np.int32)
LAG1_TO_LAG2 = np.array([LAG2_INDEX_MAP[p] for p in LAG1_OFFSETS], dtype=np.int32)

_r2 = np.array([dy**2 + dx**2 for dy, dx in LAG3_OFFSETS], dtype=np.float64)
WAR_WEIGHTS = 1.0 / (1.0 + 0.25 * _r2)
WAR_WEIGHTS_NORM = WAR_WEIGHTS / np.sum(WAR_WEIGHTS)


def map_ar_coeffs(
    coeffs: Sequence[int],
    src_lag: int,
    target_lag: int,
    is_chroma: bool = False,
    src_shift: int = 6,
    target_shift: int = 6,
) -> list[float]:
    target_spatial = 2 * target_lag * (target_lag + 1)
    target_total = target_spatial + 1 if is_chroma else target_spatial
    result = [0.0] * target_total
    if not coeffs:
        return result

    scale_factor = 2.0 ** (target_shift - src_shift)
    src_spatial = 2 * src_lag * (src_lag + 1)

    if src_lag > 0 and target_lag > 0:
        if src_lag == target_lag:
            n_sp = min(len(coeffs), target_spatial)
            for i in range(n_sp):
                result[i] = coeffs[i] * scale_factor
        elif target_lag == 3:
            if src_lag == 2:
                n_sp = min(len(coeffs), len(LAG2_TO_LAG3))
                for i in range(n_sp):
                    result[LAG2_TO_LAG3[i]] = coeffs[i] * scale_factor
            elif src_lag == 1:
                n_sp = min(len(coeffs), len(LAG1_TO_LAG3))
                for i in range(n_sp):
                    result[LAG1_TO_LAG3[i]] = coeffs[i] * scale_factor
        elif target_lag == 2:
            if src_lag == 1:
                n_sp = min(len(coeffs), len(LAG1_TO_LAG2))
                for i in range(n_sp):
                    result[LAG1_TO_LAG2[i]] = coeffs[i] * scale_factor
            elif src_lag == 3:
                # Down-mapping from Lag 3 to Lag 2
                for i in range(len(LAG2_TO_LAG3)):
                    idx3 = int(LAG2_TO_LAG3[i])
                    if idx3 < len(coeffs):
                        result[i] = coeffs[idx3] * scale_factor
        elif target_lag == 1:
            if src_lag == 3:
                for i in range(len(LAG1_TO_LAG3)):
                    idx3 = int(LAG1_TO_LAG3[i])
                    if idx3 < len(coeffs):
                        result[i] = coeffs[idx3] * scale_factor
            elif src_lag == 2:
                for i in range(len(LAG1_TO_LAG2)):
                    idx2 = int(LAG1_TO_LAG2[i])
                    if idx2 < len(coeffs):
                        result[i] = coeffs[idx2] * scale_factor

    if is_chroma and len(coeffs) > src_spatial:
        luma_mult = coeffs[src_spatial]
        result[target_spatial] = luma_mult * scale_factor

    return result


def embed_ar_coeffs_24d(coeffs: Sequence[int], lag: int, ar_shift: int = 6) -> np.ndarray:
    vec = np.zeros(24, dtype=np.float64)
    if not coeffs or lag == 0:
        return vec
    scale = 2.0 ** (6 - ar_shift)
    raw = np.asarray(coeffs, dtype=np.float64) * scale
    if lag == 3:
        n = min(len(raw), 24)
        vec[:n] = raw[:n]
    elif lag == 2:
        n = min(len(raw), len(LAG2_TO_LAG3))
        vec[LAG2_TO_LAG3[:n]] = raw[:n]
    elif lag == 1:
        n = min(len(raw), len(LAG1_TO_LAG3))
        vec[LAG1_TO_LAG3[:n]] = raw[:n]
    return vec


def compute_war_distance(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    diff = vec_a - vec_b
    return float(np.sqrt(np.sum(WAR_WEIGHTS_NORM * (diff ** 2))))


def _event_flags(ev: dict) -> tuple[int, int]:
    ag = 1 if fgs_parser.get_apply_grain(ev) != 0 else 0
    up = 0 if ag == 0 else (1 if fgs_parser.get_update_parameters(ev) != 0 else 0)
    return ag, up


def event_has_grain(ev: dict) -> bool:
    if fgs_parser.get_apply_grain(ev) == 0:
        return False
    sd = ev.get("scale_data") or {}
    for plane in ("sY", "sCb", "sCr"):
        ys = sd.get(plane, {}).get("y", [])
        if any(y > 0 for y in ys):
            return True
    return False


_CACHE_KEYS = ("_ar_coeffs", "_norm_sY", "_norm_sCb", "_norm_sCr")


def resolve_effective_events(
    raw_events: Sequence[dict],
) -> tuple[list[dict], list[int], list[int]]:
    eff_events: list[dict] = []
    eff_ag: list[int] = []
    eff_up: list[int] = []
    last_master: dict | None = None

    for ev in raw_events:
        ag, up = _event_flags(ev)
        seed = fgs_parser.get_grain_seed(ev)
        st = int(ev.get("start_time", 0))
        et = int(ev.get("end_time", st + 1))

        if ag == 0:
            wrapper = {k: v for k, v in ev.items() if k not in _CACHE_KEYS}
            wrapper["extra_params"] = ["0", str(seed), "0"]
            wrapper["e_line"] = f"E {st} {et} 0 {seed} 0\n"
            wrapper["scale_data"] = {
                "sY": {"x": [], "y": []},
                "sCb": {"x": [], "y": []},
                "sCr": {"x": [], "y": []},
            }
            wrapper["p_params"] = dict(fgs_parser.P_DEFAULTS)
            wrapper["raw_lines"] = []
            eff_events.append(wrapper)
            eff_ag.append(0)
            eff_up.append(0)
            continue

        if up == 0:
            if last_master is not None:
                wrapper = {k: v for k, v in ev.items() if k not in _CACHE_KEYS}
                wrapper["extra_params"] = ["1", str(seed), "0"]
                wrapper["e_line"] = f"E {st} {et} 1 {seed} 0\n"
                wrapper["p_params"] = last_master.get("p_params") or fgs_parser.P_DEFAULTS
                wrapper["scale_data"] = last_master.get("scale_data") or {}
                wrapper["raw_lines"] = last_master.get("raw_lines", [])
                for ck in _CACHE_KEYS:
                    if ck in last_master:
                        wrapper[ck] = last_master[ck]
                eff_events.append(wrapper)
                eff_ag.append(1)
                eff_up.append(0)
            else:
                wrapper = dict(ev)
                wrapper["extra_params"] = ["1", str(seed), "1"]
                wrapper["e_line"] = f"E {st} {et} 1 {seed} 1\n"
                last_master = wrapper
                eff_events.append(wrapper)
                eff_ag.append(1)
                eff_up.append(1)
            continue

        last_master = ev
        eff_events.append(ev)
        eff_ag.append(1)
        eff_up.append(1)

    return eff_events, eff_ag, eff_up


def are_scenes_merge_compatible(prev_ev: dict, curr_ev: dict) -> bool:
    ag_prev, up_prev = _event_flags(prev_ev)
    ag_curr, up_curr = _event_flags(curr_ev)
    if ag_prev != ag_curr:
        return False
    if ag_prev == 0:
        return True
    if up_prev == 0 and up_curr == 1:
        return False
    return True


def ensure_valid_afgs1_chain(events: list[dict]) -> list[dict]:
    have_active_model = False
    for ev in events:
        ag, up = _event_flags(ev)
        seed = fgs_parser.get_grain_seed(ev)
        if ag == 0:
            up = 0
        else:
            if up == 0 and not have_active_model:
                up = 1
            if up == 1:
                have_active_model = True
        extra = [str(ag), str(seed), str(up)]
        ev["extra_params"] = extra
        st = int(ev.get("start_time", 0))
        et = int(ev.get("end_time", st + 1))
        ev["e_line"] = f"E {st} {et} {' '.join(extra)}\n"
    return events


def update_scene_equivalence_flags(events: list[dict]) -> None:
    for idx in range(len(events)):
        if idx == 0:
            events[idx]["is_equivalent_with_prev"] = False
            continue
        prev_ev = events[idx - 1]
        curr_ev = events[idx]
        if not are_scenes_merge_compatible(prev_ev, curr_ev):
            curr_ev["is_equivalent_with_prev"] = False
            continue
        ag_prev, _ = _event_flags(prev_ev)
        if ag_prev == 0:
            curr_ev["is_equivalent_with_prev"] = True
            continue
        prev_s = prev_ev.get("apparent_strength", 0.0)
        curr_s = curr_ev.get("apparent_strength", 0.0)
        max_s = max(prev_s, curr_s, 0.01)
        diff_ratio = abs(curr_s - prev_s) / max_s
        curr_ev["is_equivalent_with_prev"] = diff_ratio <= 0.03


def get_event_ar_coeffs(ev: dict) -> tuple[list[int], list[int], list[int]]:
    if "_ar_coeffs" in ev:
        return ev["_ar_coeffs"]
    res = fgs_parser.extract_ar_coeffs_from_raw_lines(ev.get("raw_lines", []))
    ev["_ar_coeffs"] = res
    return res


def get_event_normalized_curve(ev: dict, plane: str = "sY") -> np.ndarray:
    cache_key = "_norm_" + plane
    if cache_key in ev:
        return ev[cache_key]
    sd = ev.get("scale_data") or {}
    ch = sd.get(plane, {})
    xs = ch.get("x", [])
    ys = ch.get("y", [])
    if not xs or not ys:
        arr = np.zeros(256, dtype=np.float64)
        ev[cache_key] = arr
        return arr
    p = ev.get("p_params") or fgs_parser.P_DEFAULTS
    shift = p.get("scaling_shift", 8)
    scale = 2.0 ** (8 - shift)
    arr = interpolate_scaling_curve(xs, ys) * scale
    ev[cache_key] = arr
    return arr


def compute_safe_anti_clipping_envelope(
    luma_min: int,
    luma_max: int,
    scaling_shift: int,
    is_full_range: bool = False,
    is_chroma: bool = False,
) -> list[float]:

    total_shift = scaling_shift + 4
    divisor = 1 << total_shift

    abs_min = abs(luma_min) if luma_min != 0 else 1
    abs_max = abs(luma_max) if luma_max != 0 else 1

    l_min = 0 if is_full_range else 16
    l_max = 255 if is_full_range else (240 if is_chroma else 235)

    safe_envelope = [0.0] * 256
    for x in range(256):
        if x <= l_min or x >= l_max:
            safe_envelope[x] = 0.0
        else:
            y_black = ((x - l_min) * divisor) / abs_min
            y_white = ((l_max - x) * divisor) / abs_max
            safe_envelope[x] = max(0.0, min(255.0, y_black, y_white))

    return safe_envelope


def interpolate_scaling_curve(xs: Sequence[int], ys: Sequence[int]) -> np.ndarray:
    if not xs or not ys:
        return np.zeros(256, dtype=np.float64)
    return np.interp(np.arange(256), np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64))


def calculate_curve_diff(
    ys_a: Sequence[float] | np.ndarray,
    ys_b: Sequence[float] | np.ndarray,
    x_range: Sequence[int] | None = None,
) -> tuple[float, float]:
    arr_a = np.asarray(ys_a, dtype=np.float64)
    arr_b = np.asarray(ys_b, dtype=np.float64)
    if x_range is not None:
        sub_a = arr_a[list(x_range)]
        sub_b = arr_b[list(x_range)]
        diffs = np.abs(sub_a - sub_b)
    else:
        diffs = np.abs(arr_a - arr_b)
    if len(diffs) == 0:
        return 0.0, 0.0
    return float(np.mean(diffs)), float(np.max(diffs))


def are_events_similar(
    ev_a: dict,
    ev_b: dict,
    ignore_chroma: bool = True,
    is_full_range: bool = False,
    luma_mae_th: float = 2.0,
    luma_max_th: float = 4.0,
    chroma_mae_th: float = 4.0,
    chroma_max_th: float = 8.0,
    ar_coeff_th: float = 6.0,
    weber_th: float = 1.45,
) -> bool:
    ag_a, _ = _event_flags(ev_a)
    ag_b, up_b = _event_flags(ev_b)
    if ag_a != ag_b:
        return False
    if ag_a == 0:
        return True
    if up_b == 0:
        return True

    p_a = ev_a.get("p_params") or fgs_parser.P_DEFAULTS
    p_b = ev_b.get("p_params") or fgs_parser.P_DEFAULTS

    if p_a.get("overlap_flag", 1) != p_b.get("overlap_flag", 1):
        return False
    if p_a.get("chroma_scaling_from_luma", 0) != p_b.get("chroma_scaling_from_luma", 0):
        return False

    grain_a = event_has_grain(ev_a)
    grain_b = event_has_grain(ev_b)
    if grain_a != grain_b:
        return False
    if not grain_a and not grain_b:
        return True

    sy_a = get_event_normalized_curve(ev_a, "sY")
    sy_b = get_event_normalized_curve(ev_b, "sY")

    e_slice = slice(0, 256) if is_full_range else slice(16, 236)
    e_a = float(np.mean(sy_a[e_slice]))
    e_b = float(np.mean(sy_b[e_slice]))
    if e_a > 0 and e_b > 0:
        ratio = (max(e_a, e_b) + 6.0) / (min(e_a, e_b) + 6.0)
        if ratio > weber_th:
            return False
    max_a = float(np.max(sy_a))
    max_b = float(np.max(sy_b))
    if max_a > 0 and max_b > 0:
        ratio_max = (max(max_a, max_b) + 6.0) / (min(max_a, max_b) + 6.0)
        if ratio_max > weber_th:
            return False

    cy_a, cb_a, cr_a = get_event_ar_coeffs(ev_a)
    cy_b, cb_b, cr_b = get_event_ar_coeffs(ev_b)
    lag_a = p_a.get("ar_coeff_lag", 3)
    lag_b = p_b.get("ar_coeff_lag", 3)
    shift_a = p_a.get("ar_coeff_shift", 6)
    shift_b = p_b.get("ar_coeff_shift", 6)

    vec_a = embed_ar_coeffs_24d(cy_a, lag_a, shift_a)
    vec_b = embed_ar_coeffs_24d(cy_b, lag_b, shift_b)
    d_war = compute_war_distance(vec_a, vec_b)
    if d_war > ar_coeff_th:
        return False

    mae_y, max_y = calculate_curve_diff(sy_a, sy_b)
    if mae_y > luma_mae_th or max_y > luma_max_th:
        return False

    if not ignore_chroma:
        scale_a = ev_a.get("scale_data") or {}
        scale_b = ev_b.get("scale_data") or {}
        has_cb_a = bool(scale_a.get("sCb", {}).get("y"))
        has_cb_b = bool(scale_b.get("sCb", {}).get("y"))
        has_cr_a = bool(scale_a.get("sCr", {}).get("y"))
        has_cr_b = bool(scale_b.get("sCr", {}).get("y"))

        if has_cb_a != has_cb_b or has_cr_a != has_cr_b:
            return False

        if p_a.get("chroma_scaling_from_luma", 0) == 0:
            for k in ("cb_mult", "cb_luma_mult", "cr_mult", "cr_luma_mult"):
                if abs(p_a.get(k, 128) - p_b.get(k, 128)) > 8:
                    return False
            for k in ("cb_offset", "cr_offset"):
                if abs(p_a.get(k, 256) - p_b.get(k, 256)) > 16:
                    return False

        scb_a = get_event_normalized_curve(ev_a, "sCb")
        scb_b = get_event_normalized_curve(ev_b, "sCb")
        mae_cb, max_cb = calculate_curve_diff(scb_a, scb_b)
        if mae_cb > chroma_mae_th or max_cb > chroma_max_th:
            return False

        scr_a = get_event_normalized_curve(ev_a, "sCr")
        scr_b = get_event_normalized_curve(ev_b, "sCr")
        mae_cr, max_cr = calculate_curve_diff(scr_a, scr_b)
        if mae_cr > chroma_mae_th or max_cr > chroma_max_th:
            return False

    return True


def ramer_douglas_peucker(points: list[tuple[float, float]], epsilon: float) -> list[tuple[float, float]]:
    if len(points) <= 2:
        return list(points)

    p1 = points[0]
    p2 = points[-1]
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    norm = math.hypot(dx, dy)

    max_dist = 0.0
    index = 0
    for i in range(1, len(points) - 1):
        p = points[i]
        if norm == 0:
            dist = math.hypot(p[0] - p1[0], p[1] - p1[1])
        else:
            dist = abs(dy * p[0] - dx * p[1] + p2[0] * p1[1] - p2[1] * p1[0]) / norm
        if dist > max_dist:
            max_dist = dist
            index = i

    if max_dist > epsilon:
        left = ramer_douglas_peucker(points[: index + 1], epsilon)
        right = ramer_douglas_peucker(points[index:], epsilon)
        return left[:-1] + right
    else:
        return [p1, p2]


def fit_curve_rdp(
    sampled_ys: Sequence[float],
    max_points: int = 14,
    is_full_range: bool = False,
    safe_envelope: Sequence[float] | None = None,
    is_chroma: bool = False,
) -> tuple[list[int], list[int]]:
    clamped_ys = [float(y) for y in sampled_ys]
    if safe_envelope is not None:
        for x in range(min(len(clamped_ys), len(safe_envelope))):
            clamped_ys[x] = max(0.0, min(clamped_ys[x], safe_envelope[x]))

    l_min = 0 if is_full_range else 16
    l_max = 255 if is_full_range else (240 if is_chroma else 235)

    max_val = max(clamped_ys[l_min : l_max + 1]) if l_max >= l_min else 0.0
    if max_val < 0.5:
        return [], []

    start_x = l_min
    end_x = l_max
    while start_x < l_max and clamped_ys[start_x] < 0.1:
        start_x += 1
    while end_x > l_min and clamped_ys[end_x] < 0.1:
        end_x -= 1

    if not is_full_range:
        start_x = min(16, start_x)
        end_x = max(240 if is_chroma else 235, end_x)

    pts = [(float(x), float(clamped_ys[x])) for x in range(start_x, end_x + 1)]
    if len(pts) <= max_points:
        chosen_pts = pts
    else:
        low_eps = 0.05
        high_eps = 100.0
        best_pts = pts
        for _ in range(16):
            mid_eps = (low_eps + high_eps) / 2.0
            simplified = ramer_douglas_peucker(pts, mid_eps)
            if len(simplified) <= max_points:
                best_pts = simplified
                high_eps = mid_eps
            else:
                low_eps = mid_eps
            if high_eps - low_eps < 0.05:
                break
        chosen_pts = best_pts

    xs: list[int] = []
    ys: list[int] = []
    last_x = -1
    max_allowed_x = 255 if is_full_range else (240 if is_chroma else 235)
    for px, py in chosen_pts:
        ix = int(round(px))
        iy = int(round(py))
        iy = max(0, min(255, iy))

        if ix <= last_x:
            ix = last_x + 1
        if ix > max_allowed_x:
            break

        if safe_envelope is not None and ix < len(safe_envelope):
            iy = min(iy, int(math.floor(safe_envelope[ix])))

        xs.append(ix)
        ys.append(iy)
        last_x = ix

    if len(xs) > max_points:
        while len(xs) > max_points:
            min_area = float("inf")
            idx_to_remove = 1
            for i in range(1, len(xs) - 1):
                area = abs(xs[i] * (ys[i + 1] - ys[i - 1]) + xs[i - 1] * (ys[i] - ys[i + 1]) + xs[i + 1] * (ys[i - 1] - ys[i]))
                if area < min_area:
                    min_area = area
                    idx_to_remove = i
            xs.pop(idx_to_remove)
            ys.pop(idx_to_remove)

    return xs, ys


def get_raw_events_in_range(
    all_raw_events: Sequence[dict],
    t_start: int,
    t_end: int,
) -> list[dict]:

    if not all_raw_events:
        return []

    matching = [
        ev for ev in all_raw_events
        if ev["start_time"] < t_end and ev["end_time"] > t_start
    ]
    if matching:
        return matching

    mid_target = (t_start + t_end) / 2.0
    closest = min(
        all_raw_events,
        key=lambda ev: abs(((ev["start_time"] + ev["end_time"]) / 2.0) - mid_target),
    )
    return [closest]


def consolidate_raw_events(
    raw_events: Sequence[dict],
    t_start: int,
    t_end: int,
    is_full_range: bool = False,
    ignore_chroma: bool = True,
    skip_simulation: bool = False,
    is_444: bool = False,
    bit_depth: int = 8,
    effective_events: Sequence[dict] | None = None,
    inherited_master: dict | None = None,
) -> dict:

    if not raw_events:
        raise ValueError("Cannot consolidate an empty list of raw events.")

    n = len(raw_events)
    start_time = int(t_start)
    end_time = int(t_end)
    seed = fgs_parser.get_grain_seed(raw_events[0])
    flags = [_event_flags(ev) for ev in raw_events]

    if all(ag == 0 for ag, _ in flags):
        extra_params = ["0", str(seed), "0"]
        return {
            "start_time": start_time,
            "end_time": end_time,
            "e_line": f"E {start_time} {end_time} 0 {seed} 0\n",
            "extra_params": extra_params,
            "raw_lines": [],
            "scale_data": {
                "sY": {"x": [], "y": []},
                "sCb": {"x": [], "y": []},
                "sCr": {"x": [], "y": []},
            },
            "p_params": dict(fgs_parser.P_DEFAULTS),
            "raw_events_count": n,
        }

    if all(ag == 1 and up == 0 for ag, up in flags) and inherited_master is not None:
        extra_params = ["1", str(seed), "0"]
        empty_sd = {
            "sY": {"x": [], "y": []},
            "sCb": {"x": [], "y": []},
            "sCr": {"x": [], "y": []},
        }
        return {
            "start_time": start_time,
            "end_time": end_time,
            "e_line": f"E {start_time} {end_time} 1 {seed} 0\n",
            "extra_params": extra_params,
            "raw_lines": list(inherited_master.get("raw_lines", [])),
            "scale_data": copy.deepcopy(inherited_master.get("scale_data") or empty_sd),
            "p_params": copy.deepcopy(inherited_master.get("p_params") or fgs_parser.P_DEFAULTS),
            "raw_events_count": n,
        }

    if effective_events is not None:
        resolved = [
            eff for eff, (ag, _) in zip(effective_events, flags) if ag == 1
        ] or list(effective_events)
    else:
        resolved_all, resolved_ag, _ = resolve_effective_events(raw_events)
        resolved = [
            eff for eff, ag in zip(resolved_all, resolved_ag) if ag == 1
        ] or resolved_all
    src_n = len(resolved)

    base_p = resolved[0].get("p_params") or fgs_parser.P_DEFAULTS
    avg_scaling_shift = int(round(sum((ev.get("p_params") or base_p).get("scaling_shift", 8) for ev in resolved) / src_n))
    lag_durations: dict[int, int] = {}
    for ev in resolved:
        ev_lag = (ev.get("p_params") or base_p).get("ar_coeff_lag", 3)
        dur = max(1, int(ev.get("end_time", 0)) - int(ev.get("start_time", 0)))
        lag_durations[ev_lag] = lag_durations.get(ev_lag, 0) + dur
    avg_ar_lag = min(lag_durations.keys(), key=lambda l: (-lag_durations[l], l))
    avg_ar_shift = int(round(sum((ev.get("p_params") or base_p).get("ar_coeff_shift", 6) for ev in resolved) / src_n))
    avg_cb_mult = int(round(sum((ev.get("p_params") or base_p).get("cb_mult", 128) for ev in resolved) / src_n))
    avg_cb_luma_mult = int(round(sum((ev.get("p_params") or base_p).get("cb_luma_mult", 192) for ev in resolved) / src_n))
    avg_cb_offset = int(round(sum((ev.get("p_params") or base_p).get("cb_offset", 256) for ev in resolved) / src_n))
    avg_cr_mult = int(round(sum((ev.get("p_params") or base_p).get("cr_mult", 128) for ev in resolved) / src_n))
    avg_cr_luma_mult = int(round(sum((ev.get("p_params") or base_p).get("cr_luma_mult", 192) for ev in resolved) / src_n))
    avg_cr_offset = int(round(sum((ev.get("p_params") or base_p).get("cr_offset", 256) for ev in resolved) / src_n))
    overlap_flag = base_p.get("overlap_flag", 1)
    chroma_scaling_from_luma = base_p.get("chroma_scaling_from_luma", 0)
    grain_scale_shift = base_p.get("grain_scale_shift", 0)

    merged_p = {
        "scaling_shift": avg_scaling_shift,
        "ar_coeff_lag": avg_ar_lag,
        "ar_coeff_shift": avg_ar_shift,
        "grain_scale_shift": grain_scale_shift,
        "cb_mult": avg_cb_mult,
        "cb_luma_mult": avg_cb_luma_mult,
        "cb_offset": avg_cb_offset,
        "cr_mult": avg_cr_mult,
        "cr_luma_mult": avg_cr_luma_mult,
        "cr_offset": avg_cr_offset,
        "overlap_flag": overlap_flag,
        "chroma_scaling_from_luma": chroma_scaling_from_luma,
    }

    expected_cy = fgs_parser._expected_ar_count(avg_ar_lag, "cY")
    expected_cb = fgs_parser._expected_ar_count(avg_ar_lag, "cCb")
    expected_cr = fgs_parser._expected_ar_count(avg_ar_lag, "cCr")

    sum_cy = [0.0] * expected_cy
    sum_cb = [0.0] * expected_cb
    sum_cr = [0.0] * expected_cr

    for ev in resolved:
        cy, cb, cr = get_event_ar_coeffs(ev)
        p = ev.get("p_params") or base_p
        ev_lag = p.get("ar_coeff_lag", avg_ar_lag)
        ev_shift = p.get("ar_coeff_shift", avg_ar_shift)

        mapped_cy = map_ar_coeffs(cy, ev_lag, avg_ar_lag, is_chroma=False, src_shift=ev_shift, target_shift=avg_ar_shift)
        mapped_cb = map_ar_coeffs(cb, ev_lag, avg_ar_lag, is_chroma=True, src_shift=ev_shift, target_shift=avg_ar_shift)
        mapped_cr = map_ar_coeffs(cr, ev_lag, avg_ar_lag, is_chroma=True, src_shift=ev_shift, target_shift=avg_ar_shift)

        for i in range(expected_cy):
            sum_cy[i] += mapped_cy[i]
        for i in range(expected_cb):
            sum_cb[i] += mapped_cb[i]
        for i in range(expected_cr):
            sum_cr[i] += mapped_cr[i]

    merged_cy = [int(round(val / src_n)) for val in sum_cy]
    merged_cb = [int(round(val / src_n)) for val in sum_cb]
    merged_cr = [int(round(val / src_n)) for val in sum_cr]

    merged_cy = [max(-128, min(127, c)) for c in merged_cy]
    merged_cb = [max(-128, min(127, c)) for c in merged_cb]
    merged_cr = [max(-128, min(127, c)) for c in merged_cr]

    extremes: dict | None = None
    if not skip_simulation:
        extremes = fgs_grain_sim.compute_grain_extremes(
            seed=seed,
            cy_coeffs=merged_cy,
            cb_coeffs=merged_cb,
            cr_coeffs=merged_cr,
            ar_lag=avg_ar_lag,
            ar_shift=avg_ar_shift,
            grain_scale_shift=0,
            is_444=is_444,
        )

        safe_envelope_y = compute_safe_anti_clipping_envelope(
            extremes["luma_min"], extremes["luma_max"], avg_scaling_shift, is_full_range=is_full_range, is_chroma=False
        )
        safe_envelope_cb = compute_safe_anti_clipping_envelope(
            extremes["cb_min"], extremes["cb_max"], avg_scaling_shift, is_full_range=is_full_range, is_chroma=True
        )
        safe_envelope_cr = compute_safe_anti_clipping_envelope(
            extremes["cr_min"], extremes["cr_max"], avg_scaling_shift, is_full_range=is_full_range, is_chroma=True
        )
    else:
        safe_envelope_y = None
        safe_envelope_cb = None
        safe_envelope_cr = None

    dense_norm_y = np.zeros(256, dtype=np.float64)
    dense_norm_cb = np.zeros(256, dtype=np.float64)
    dense_norm_cr = np.zeros(256, dtype=np.float64)

    for ev in resolved:
        dense_norm_y += get_event_normalized_curve(ev, "sY")
        dense_norm_cb += get_event_normalized_curve(ev, "sCb")
        dense_norm_cr += get_event_normalized_curve(ev, "sCr")

    dense_norm_y /= src_n
    dense_norm_cb /= src_n
    dense_norm_cr /= src_n

    scale_from_norm = 2.0 ** (avg_scaling_shift - 8)
    dense_sy = dense_norm_y * scale_from_norm
    dense_scb = dense_norm_cb * scale_from_norm
    dense_scr = dense_norm_cr * scale_from_norm

    fit_xs_y, fit_ys_y = fit_curve_rdp(dense_sy, max_points=14, is_full_range=is_full_range, safe_envelope=safe_envelope_y, is_chroma=False)
    if chroma_scaling_from_luma == 1:
        fit_xs_cb, fit_ys_cb = [], []
        fit_xs_cr, fit_ys_cr = [], []
    else:
        fit_xs_cb, fit_ys_cb = fit_curve_rdp(dense_scb, max_points=10, is_full_range=is_full_range, safe_envelope=safe_envelope_cb, is_chroma=True)
        fit_xs_cr, fit_ys_cr = fit_curve_rdp(dense_scr, max_points=10, is_full_range=is_full_range, safe_envelope=safe_envelope_cr, is_chroma=True)

    if not skip_simulation and extremes is None:
        extremes = fgs_grain_sim.compute_grain_extremes(
            seed=seed,
            cy_coeffs=merged_cy,
            cb_coeffs=merged_cb,
            cr_coeffs=merged_cr,
            ar_lag=avg_ar_lag,
            ar_shift=avg_ar_shift,
            grain_scale_shift=0,
            is_444=is_444,
        )

    if extremes:
        if fit_xs_y and fit_ys_y:
            fit_xs_y, _ = fgs_grain_sim.fix_channel_clipping(
                fit_xs_y,
                fit_ys_y,
                "sY",
                grain_min=extremes.get("luma_min", 0),
                grain_max=extremes.get("luma_max", 0),
                scaling_shift=avg_scaling_shift,
                bit_depth=bit_depth,
                is_full_range=is_full_range,
            )
        if chroma_scaling_from_luma != 1:
            if fit_xs_cb and fit_ys_cb:
                fit_xs_cb, _ = fgs_grain_sim.fix_channel_clipping(
                    fit_xs_cb,
                    fit_ys_cb,
                    "sCb",
                    grain_min=extremes.get("cb_min", 0),
                    grain_max=extremes.get("cb_max", 0),
                    scaling_shift=avg_scaling_shift,
                    bit_depth=bit_depth,
                    is_full_range=is_full_range,
                )
            if fit_xs_cr and fit_ys_cr:
                fit_xs_cr, _ = fgs_grain_sim.fix_channel_clipping(
                    fit_xs_cr,
                    fit_ys_cr,
                    "sCr",
                    grain_min=extremes.get("cr_min", 0),
                    grain_max=extremes.get("cr_max", 0),
                    scaling_shift=avg_scaling_shift,
                    bit_depth=bit_depth,
                    is_full_range=is_full_range,
                )

    scale_data = {
        "sY": {"x": fit_xs_y, "y": fit_ys_y},
        "sCb": {"x": fit_xs_cb, "y": fit_ys_cb},
        "sCr": {"x": fit_xs_cr, "y": fit_ys_cr},
    }

    raw_lines: list[str] = []
    p_tokens = fgs_parser.p_params_to_tokens(merged_p)
    raw_lines.append(f"  p {' '.join(p_tokens)}\n")

    for ch, xs, ys in [("sY", fit_xs_y, fit_ys_y), ("sCb", fit_xs_cb, fit_ys_cb), ("sCr", fit_xs_cr, fit_ys_cr)]:
        if not xs:
            raw_lines.append(f"  {ch} 0\n")
        else:
            pairs = []
            for x, y in zip(xs, ys):
                pairs.extend([str(x), str(y)])
            raw_lines.append(f"  {ch} {len(xs)}  {' '.join(pairs)}\n")

    raw_lines.append(fgs_parser.format_c_line("cY", merged_cy, avg_ar_lag))
    raw_lines.append(fgs_parser.format_c_line("cCb", merged_cb, avg_ar_lag))
    raw_lines.append(fgs_parser.format_c_line("cCr", merged_cr, avg_ar_lag))

    extra_params = ["1", str(seed), "1"]
    e_line = f"E {start_time} {end_time} {' '.join(extra_params)}\n"

    return {
        "start_time": start_time,
        "end_time": end_time,
        "e_line": e_line,
        "extra_params": extra_params,
        "raw_lines": raw_lines,
        "scale_data": scale_data,
        "p_params": merged_p,
        "raw_events_count": n,
    }


def resolve_overlapping_windows(
    candidate_windows: Sequence[dict],
    all_raw_events: Sequence[dict],
    is_full_range: bool = False,
    ignore_chroma: bool = True,
    skip_simulation: bool = False,
    luma_mae_th: float = 2.0,
    luma_max_th: float = 4.0,
    ar_coeff_th: float = 6.0,
    chroma_mae_th: float = 4.0,
    chroma_max_th: float = 8.0,
    is_444: bool = False,
    bit_depth: int = 8,
) -> list[dict]:

    if not candidate_windows:
        return []

    sorted_windows = sorted(candidate_windows, key=lambda w: (w["start_time"], w["end_time"]))
    resolved: list[dict] = [sorted_windows[0]]

    for next_w in sorted_windows[1:]:
        prev_w = resolved[-1]
        t0 = prev_w["start_time"]
        t2 = prev_w["end_time"]
        t1 = next_w["start_time"]
        t3 = next_w["end_time"]

        if t1 >= t2:
            if t1 > t2:
                prev_raw = get_raw_events_in_range(all_raw_events, t0, t1)
                resolved[-1] = consolidate_raw_events(
                    prev_raw,
                    t0,
                    t1,
                    is_full_range=is_full_range,
                    ignore_chroma=ignore_chroma,
                    skip_simulation=skip_simulation,
                    is_444=is_444,
                    bit_depth=bit_depth,
                )
            resolved.append(next_w)
            continue

        if t3 <= t2:
            if are_events_similar(
                prev_w, next_w, ignore_chroma=ignore_chroma, is_full_range=is_full_range,
                luma_mae_th=luma_mae_th, luma_max_th=luma_max_th, ar_coeff_th=ar_coeff_th,
                chroma_mae_th=chroma_mae_th, chroma_max_th=chroma_max_th,
            ):
                continue
            else:
                sub_events = []
                if t1 > t0:
                    raw_1 = get_raw_events_in_range(all_raw_events, t0, t1)
                    sub_events.append(consolidate_raw_events(raw_1, t0, t1, is_full_range=is_full_range, ignore_chroma=ignore_chroma, skip_simulation=skip_simulation, is_444=is_444, bit_depth=bit_depth))
                if t3 > t1:
                    raw_2 = get_raw_events_in_range(all_raw_events, t1, t3)
                    sub_events.append(consolidate_raw_events(raw_2, t1, t3, is_full_range=is_full_range, ignore_chroma=ignore_chroma, skip_simulation=skip_simulation, is_444=is_444, bit_depth=bit_depth))
                if t2 > t3:
                    raw_3 = get_raw_events_in_range(all_raw_events, t3, t2)
                    sub_events.append(consolidate_raw_events(raw_3, t3, t2, is_full_range=is_full_range, ignore_chroma=ignore_chroma, skip_simulation=skip_simulation, is_444=is_444, bit_depth=bit_depth))

                resolved.pop()
                resolved.extend(sub_events)
                continue

        if are_events_similar(
            prev_w, next_w, ignore_chroma=ignore_chroma, is_full_range=is_full_range,
            luma_mae_th=luma_mae_th, luma_max_th=luma_max_th, ar_coeff_th=ar_coeff_th,
            chroma_mae_th=chroma_mae_th, chroma_max_th=chroma_max_th,
        ):
            raw_union = get_raw_events_in_range(all_raw_events, t0, t3)
            unified = consolidate_raw_events(raw_union, t0, t3, is_full_range=is_full_range, ignore_chroma=ignore_chroma, skip_simulation=skip_simulation, is_444=is_444, bit_depth=bit_depth)
            resolved[-1] = unified
        else:
            sub_events = []
            if t1 > t0:
                raw_1 = get_raw_events_in_range(all_raw_events, t0, t1)
                sub_events.append(consolidate_raw_events(raw_1, t0, t1, is_full_range=is_full_range, ignore_chroma=ignore_chroma, skip_simulation=skip_simulation, is_444=is_444, bit_depth=bit_depth))
            if t2 > t1:
                raw_2 = get_raw_events_in_range(all_raw_events, t1, t2)
                sub_events.append(consolidate_raw_events(raw_2, t1, t2, is_full_range=is_full_range, ignore_chroma=ignore_chroma, skip_simulation=skip_simulation, is_444=is_444, bit_depth=bit_depth))
            if t3 > t2:
                raw_3 = get_raw_events_in_range(all_raw_events, t2, t3)
                sub_events.append(consolidate_raw_events(raw_3, t2, t3, is_full_range=is_full_range, ignore_chroma=ignore_chroma, skip_simulation=skip_simulation, is_444=is_444, bit_depth=bit_depth))

            resolved.pop()
            resolved.extend(sub_events)

    return resolved


def evaluate_apparent_grain_strength(event: dict) -> float:
    if fgs_parser.get_apply_grain(event) == 0:
        return 0.0

    p = event.get("p_params") or fgs_parser.P_DEFAULTS
    scaling_shift = p.get("scaling_shift", 8)
    total_shift = scaling_shift + 4
    divisor = 1 << total_shift

    cy, cb, cr = get_event_ar_coeffs(event)
    seed = fgs_parser.get_grain_seed(event)
    extremes = fgs_grain_sim.compute_grain_extremes(
        seed=seed,
        cy_coeffs=cy,
        cb_coeffs=cb,
        cr_coeffs=cr,
        ar_lag=p.get("ar_coeff_lag", 3),
        ar_shift=p.get("ar_coeff_shift", 6),
        grain_scale_shift=0,
    )
    luma_max = extremes["luma_max"]

    scale_data = event.get("scale_data") or {}
    sy = scale_data.get("sY", {})
    ys = sy.get("y", [])
    if not ys:
        return 0.0

    avg_y = sum(ys) / len(ys)
    strength = (luma_max * avg_y) / divisor
    return round(float(strength), 2)


def _are_feature_profiles_similar(
    g_a: bool,
    p_a: dict,
    y_a: np.ndarray,
    ar_a: np.ndarray,
    has_cb_a: bool,
    has_cr_a: bool,
    cb_a: np.ndarray | None,
    cr_a: np.ndarray | None,
    g_b: bool,
    p_b: dict,
    y_b: np.ndarray,
    ar_b: np.ndarray,
    has_cb_b: bool,
    has_cr_b: bool,
    cb_b: np.ndarray | None,
    cr_b: np.ndarray | None,
    *,
    ignore_chroma: bool,
    is_full_range: bool,
    luma_mae_th: float,
    luma_max_th: float,
    ar_coeff_th: float,
    chroma_mae_th: float,
    chroma_max_th: float,
    weber_th: float,
) -> bool:
    if g_a != g_b:
        return False
    if (
        p_a.get("overlap_flag", 1) != p_b.get("overlap_flag", 1)
        or p_a.get("chroma_scaling_from_luma", 0) != p_b.get("chroma_scaling_from_luma", 0)
    ):
        return False

    if g_a:
        diff = np.abs(y_a - y_b)
        if float(np.mean(diff)) > luma_mae_th or float(np.max(diff)) > luma_max_th:
            return False

        e_slice = slice(0, 256) if is_full_range else slice(16, 236)
        e1 = float(np.mean(y_a[e_slice]))
        e2 = float(np.mean(y_b[e_slice]))
        ratio = (max(e1, e2) + 6.0) / (min(e1, e2) + 6.0)
        if ratio > weber_th:
            return False
        if compute_war_distance(ar_a, ar_b) > ar_coeff_th:
            return False

    if g_a and not ignore_chroma:
        if has_cb_a != has_cb_b or has_cr_a != has_cr_b:
            return False
        if p_a.get("chroma_scaling_from_luma", 0) == 0:
            for param_name in ("cb_mult", "cb_luma_mult", "cr_mult", "cr_luma_mult"):
                if abs(p_a.get(param_name, 128) - p_b.get(param_name, 128)) > 8:
                    return False
            for param_name in ("cb_offset", "cr_offset"):
                if abs(p_a.get(param_name, 256) - p_b.get(param_name, 256)) > 16:
                    return False
        assert cb_a is not None and cb_b is not None and cr_a is not None and cr_b is not None
        diff_cb = np.abs(cb_a - cb_b)
        diff_cr = np.abs(cr_a - cr_b)
        if float(np.mean(diff_cb)) > chroma_mae_th or float(np.max(diff_cb)) > chroma_max_th:
            return False
        if float(np.mean(diff_cr)) > chroma_mae_th or float(np.max(diff_cr)) > chroma_max_th:
            return False

    return True


def optimize_dynamic_fgs(
    raw_events: Sequence[dict],
    is_full_range: bool = False,
    ignore_chroma: bool = True,
    is_444: bool = False,
    luma_mae_th: float = 2.0,
    luma_max_th: float = 4.0,
    ar_coeff_th: float = 15.0,
    chroma_mae_th: float = 4.0,
    chroma_max_th: float = 8.0,
    weber_th: float = 1.45,
    skip_simulation: bool = False,
    progress_cb: Callable[[int, str], None] | None = None,
    bit_depth: int = 8,
) -> list[dict]:

    if not raw_events:
        return []

    total_events = len(raw_events)
    if progress_cb:
        progress_cb(5, f"Scanning {total_events} raw events for coherent grain clusters...")

    eff_events, eff_ag, eff_up = resolve_effective_events(raw_events)

    feats_y = [get_event_normalized_curve(ev, "sY") for ev in eff_events]
    has_g = [event_has_grain(ev) for ev in eff_events]
    p_params = [ev.get("p_params") or fgs_parser.P_DEFAULTS for ev in eff_events]

    ar_vecs = []
    for ev, p in zip(eff_events, p_params):
        cy, cb, cr = get_event_ar_coeffs(ev)
        ar_vecs.append(embed_ar_coeffs_24d(cy, p.get("ar_coeff_lag", 3), p.get("ar_coeff_shift", 6)))

    if not ignore_chroma:
        has_cb = [bool((ev.get("scale_data") or {}).get("sCb", {}).get("y")) for ev in eff_events]
        has_cr = [bool((ev.get("scale_data") or {}).get("sCr", {}).get("y")) for ev in eff_events]
        feats_cb = [get_event_normalized_curve(ev, "sCb") for ev in eff_events]
        feats_cr = [get_event_normalized_curve(ev, "sCr") for ev in eff_events]

    clusters: list[list[int]] = []
    cur: list[int] = [0]
    c_ag = eff_ag[0]
    c_y = feats_y[0].copy()
    c_g = has_g[0]
    c_p = p_params[0]
    c_ar = ar_vecs[0].copy()
    if not ignore_chroma:
        c_has_cb = has_cb[0]
        c_has_cr = has_cr[0]
        c_cb = feats_cb[0].copy()
        c_cr = feats_cr[0].copy()

    for i in range(1, total_events):
        if i % 300 == 0 and progress_cb:
            pct = 5 + int((i / total_events) * 45)
            progress_cb(pct, f"Clustering events ({i}/{total_events})...")

        ag_i = eff_ag[i]
        up_i = eff_up[i]
        y_i = feats_y[i]
        g_i = has_g[i]
        p_i = p_params[i]
        ar_i = ar_vecs[i]

        if c_ag != ag_i:
            is_sim = False
        elif c_ag == 0:
            is_sim = True
        elif up_i == 0:
            is_sim = True
        else:
            is_sim = _are_feature_profiles_similar(
                c_g, c_p, c_y, c_ar,
                c_has_cb if not ignore_chroma else False,
                c_has_cr if not ignore_chroma else False,
                c_cb if not ignore_chroma else None,
                c_cr if not ignore_chroma else None,
                g_i, p_i, y_i, ar_i,
                has_cb[i] if not ignore_chroma else False,
                has_cr[i] if not ignore_chroma else False,
                feats_cb[i] if not ignore_chroma else None,
                feats_cr[i] if not ignore_chroma else None,
                ignore_chroma=ignore_chroma,
                is_full_range=is_full_range,
                luma_mae_th=luma_mae_th,
                luma_max_th=luma_max_th,
                ar_coeff_th=ar_coeff_th,
                chroma_mae_th=chroma_mae_th,
                chroma_max_th=chroma_max_th,
                weber_th=weber_th,
            )

        if is_sim:
            cur.append(i)
            if c_ag == 1:
                k = len(cur)
                c_y += (y_i - c_y) / k
                c_ar += (ar_i - c_ar) / k
                if not ignore_chroma and c_g:
                    c_cb += (feats_cb[i] - c_cb) / k
                    c_cr += (feats_cr[i] - c_cr) / k
        else:
            clusters.append(cur)
            cur = [i]
            c_ag = ag_i
            c_y = y_i.copy()
            c_ar = ar_i.copy()
            c_g = g_i
            c_p = p_i
            if not ignore_chroma:
                c_has_cb = has_cb[i]
                c_has_cr = has_cr[i]
                c_cb = feats_cb[i].copy()
                c_cr = feats_cr[i].copy()
    clusters.append(cur)

    if progress_cb:
        progress_cb(55, f"Formed {len(clusters)} initial candidate clusters. Merging adjacent macro-scenes...")

    merged = [clusters[0]]
    for next_c in clusters[1:]:
        prev_c = merged[-1]
        prev_ag = eff_ag[prev_c[0]]
        next_ag = eff_ag[next_c[0]]

        if prev_ag != next_ag:
            can_merge = False
        elif prev_ag == 0:
            can_merge = True
        elif eff_up[next_c[0]] == 0:
            can_merge = True
        else:
            prev_y = np.mean([feats_y[idx] for idx in prev_c], axis=0)
            next_y = np.mean([feats_y[idx] for idx in next_c], axis=0)
            prev_ar = np.mean([ar_vecs[idx] for idx in prev_c], axis=0)
            next_ar = np.mean([ar_vecs[idx] for idx in next_c], axis=0)
            prev_g = any(has_g[idx] for idx in prev_c)
            next_g = any(has_g[idx] for idx in next_c)
            p_prev = p_params[prev_c[0]]
            p_next = p_params[next_c[0]]

            can_merge = _are_feature_profiles_similar(
                prev_g,
                p_prev,
                prev_y,
                prev_ar,
                any(has_cb[idx] for idx in prev_c) if not ignore_chroma else False,
                any(has_cr[idx] for idx in prev_c) if not ignore_chroma else False,
                np.mean([feats_cb[idx] for idx in prev_c], axis=0) if not ignore_chroma else None,
                np.mean([feats_cr[idx] for idx in prev_c], axis=0) if not ignore_chroma else None,
                next_g,
                p_next,
                next_y,
                next_ar,
                any(has_cb[idx] for idx in next_c) if not ignore_chroma else False,
                any(has_cr[idx] for idx in next_c) if not ignore_chroma else False,
                np.mean([feats_cb[idx] for idx in next_c], axis=0) if not ignore_chroma else None,
                np.mean([feats_cr[idx] for idx in next_c], axis=0) if not ignore_chroma else None,
                ignore_chroma=ignore_chroma,
                is_full_range=is_full_range,
                luma_mae_th=luma_mae_th,
                luma_max_th=luma_max_th,
                ar_coeff_th=ar_coeff_th,
                chroma_mae_th=chroma_mae_th,
                chroma_max_th=chroma_max_th,
                weber_th=weber_th,
            )

        if can_merge:
            merged[-1].extend(next_c)
        else:
            merged.append(next_c)

    if progress_cb:
        progress_cb(75, f"Consolidating {len(merged)} final macro-scenes...")

    final_events: list[dict] = []
    last_emitted_master: dict | None = None
    for idx, c in enumerate(merged):
        if progress_cb and idx % 5 == 0:
            pct = 75 + int((idx / len(merged)) * 20)
            progress_cb(pct, f"Simulating safe envelopes ({idx+1}/{len(merged)})...")

        raw_slice = [raw_events[i] for i in c]
        eff_slice = [eff_events[i] for i in c]
        t_start = raw_slice[0]["start_time"]
        t_end = raw_slice[-1]["end_time"]
        final_ev = consolidate_raw_events(
            raw_slice,
            t_start,
            t_end,
            is_full_range=is_full_range,
            ignore_chroma=ignore_chroma,
            skip_simulation=skip_simulation,
            is_444=is_444,
            bit_depth=bit_depth,
            effective_events=eff_slice,
            inherited_master=last_emitted_master,
        )
        f_ag, f_up = _event_flags(final_ev)
        if f_ag == 1 and f_up == 1:
            last_emitted_master = final_ev
        final_events.append(final_ev)

    if final_events:
        final_events[0]["start_time"] = raw_events[0]["start_time"]
        final_events[-1]["end_time"] = raw_events[-1]["end_time"]
        ensure_valid_afgs1_chain(final_events)

    if progress_cb:
        progress_cb(100, f"Optimization complete: {total_events} raw events -> {len(final_events)} coherent scenes.")

    return final_events



def optimize_static_fgs(single_event: dict, is_full_range: bool = False, bit_depth: int = 8) -> dict:

    return consolidate_raw_events(
        [single_event],
        single_event["start_time"],
        single_event["end_time"],
        is_full_range=is_full_range,
        ignore_chroma=False,
        bit_depth=bit_depth,
    )


def compute_frame_ssim(img1: np.ndarray, img2: np.ndarray) -> float:

    f1 = img1.astype(np.float64)
    f2 = img2.astype(np.float64)

    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2

    mu1 = np.mean(f1)
    mu2 = np.mean(f2)
    sigma1_sq = np.var(f1)
    sigma2_sq = np.var(f2)
    sigma12 = np.mean((f1 - mu1) * (f2 - mu2))

    num = (2.0 * mu1 * mu2 + c1) * (2.0 * sigma12 + c2)
    den = (mu1**2 + mu2**2 + c1) * (sigma1_sq + sigma2_sq + c2)
    if den == 0:
        return 1.0
    return float(num / den)


def _extract_boundary_frames_and_ssim(
    video_path: str,
    timestamp_sec: float,
    width: int = 160,
    height: int = 90,
) -> float | None:
    from fgseditor_qt.tools.video_probe import find_ffmpeg
    from fgseditor_qt.core.app_paths import NO_WINDOW_FLAG

    t_start = max(0.0, timestamp_sec - 0.025)
    ffmpeg_exe = find_ffmpeg() or "ffmpeg"
    cmd = [
        ffmpeg_exe,
        "-ss", f"{t_start:.3f}",
        "-an", "-sn", "-dn",
        "-i", video_path,
        "-fps_mode", "passthrough",
        "-vframes", "2",
        "-vf", f"scale={width}:{height}",
        "-f", "rawvideo",
        "-pix_fmt", "gray",
        "-",
    ]
    run_kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.DEVNULL,
        "timeout": 6,
        "check": True,
    }
    if sys.platform == "win32" and NO_WINDOW_FLAG:
        run_kwargs["creationflags"] = NO_WINDOW_FLAG
    try:
        proc = subprocess.run(cmd, **run_kwargs)
        data = proc.stdout
        frame_bytes = width * height
        if len(data) >= frame_bytes * 2:
            f1 = np.frombuffer(data[:frame_bytes], dtype=np.uint8).astype(np.float64)
            f2 = np.frombuffer(data[frame_bytes : frame_bytes * 2], dtype=np.uint8).astype(np.float64)
            return compute_frame_ssim(f1, f2)
    except Exception:
        pass
    return None


def verify_scene_cuts(
    events: list[dict],
    video_path: str | None = None,
    scene_file: str | None = None,
    max_ssim_boundaries: int = 100,
    progress_cb: Callable[[int, str], None] | None = None,
) -> list[dict]:
    if not events:
        return events

    for idx, ev in enumerate(events):
        ev["apparent_strength"] = evaluate_apparent_grain_strength(ev)

    update_scene_equivalence_flags(events)

    if scene_file and os.path.isfile(scene_file):
        if progress_cb:
            progress_cb(90, "Verifying scene cuts using cut file...")
        cut_timestamps: list[float] = []
        try:
            with open(scene_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    try:
                        cut_timestamps.append(float(line.split()[0]))
                    except ValueError:
                        pass
        except Exception:
            pass

        for idx, ev in enumerate(events):
            if idx == 0:
                ev["cut_status"] = "[• Stream Start]"
                continue
            t_sec = ev["start_time"] / 10_000_000.0
            is_cut = any(abs(t_sec - ct) <= 0.5 for ct in cut_timestamps)
            ev["cut_status"] = "[✓ Video Scene Cut]" if is_cut else "[• Mid-Shot Shift]"

    elif video_path and os.path.isfile(video_path):
        import concurrent.futures

        num_boundaries = min(max_ssim_boundaries, len(events))
        events[0]["cut_status"] = "[• Stream Start]"

        tasks = []
        for idx in range(1, num_boundaries):
            t_sec = events[idx]["start_time"] / 10_000_000.0
            tasks.append((idx, t_sec))

        if progress_cb:
            progress_cb(90, f"Verifying {len(tasks)} boundary scene cuts in parallel...")

        max_workers = min(8, os.cpu_count() or 4)
        completed = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_idx = {
                pool.submit(_extract_boundary_frames_and_ssim, video_path, t_sec): idx
                for idx, t_sec in tasks
            }
            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                completed += 1
                if progress_cb and completed % 5 == 0:
                    pct = 90 + int((completed / len(tasks)) * 8)
                    progress_cb(pct, f"Analyzing boundary frame cuts ({completed}/{len(tasks)})...")

                try:
                    ssim = future.result()
                    if ssim is not None:
                        if ssim < 0.85:
                            events[idx]["cut_status"] = f"[✓ Video Scene Cut (SSIM: {ssim:.2f})]"
                        else:
                            events[idx]["cut_status"] = f"[• Mid-Shot Shift (SSIM: {ssim:.2f})]"
                    else:
                        events[idx]["cut_status"] = "[• Similarity Merge]"
                except Exception:
                    events[idx]["cut_status"] = "[• Similarity Merge]"

        for idx in range(num_boundaries, len(events)):
            events[idx]["cut_status"] = "[• Similarity Merge]"
    else:
        for idx, ev in enumerate(events):
            if idx == 0:
                ev["cut_status"] = "[• Stream Start]"
            else:
                ev["cut_status"] = "[• Similarity Merge]"


    if progress_cb:
        progress_cb(100, "Done!")

    return events


def build_optimized_fgs_text(events: Sequence[dict], headers: Sequence[str] | None = None) -> str:
    from fgseditor_qt.core import fgs_save

    return "".join(fgs_save.build_dynamic_lines(list(headers or []), list(events)))
