import os
import copy
from collections import deque
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QMessageBox,
    QFileDialog,
    QSizePolicy,
    QFrame,
    QComboBox,
    QLineEdit,
    QStackedWidget,
    QProgressBar,
    QCheckBox,
    QMenu,
    QDialog,
    QProgressDialog,
    QApplication,
)
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.collections import LineCollection
from matplotlib.ticker import FuncFormatter, MaxNLocator
from fgseditor_qt.core import fgs_parser
from fgseditor_qt.math import fgs_math
from fgseditor_qt.core.app_paths import get_base_dir, get_user_data_dir, is_temp_filepath
from fgseditor_qt.ui.widgets.shortcuts import create_standard_menu
from fgseditor_qt.math.time_utils import (
    COMMON_FPS,
    DEFAULT_FPS_LABEL,
    fps_from_label,
    ticks_to_frames,
    frames_to_ticks,
    ticks_to_timecode,
    timecode_to_ticks,
    ticks_to_seconds,
    seconds_to_ticks,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QCursor
import datetime
from fgseditor_qt.core.settings_manager import (
    get_setting,
    get_dialog_dir,
    update_dialog_dir,
    restore_window_geometry,
    save_window_geometry,
)

_MAX_LABELS = 100


class NonNegativeLocator(MaxNLocator):

    def tick_values(self, vmin, vmax):
        clamped_vmin = max(0.0, vmin)
        ticks = super().tick_values(clamped_vmin, vmax)
        return [t for t in ticks if t >= -1e-9]


def _get_event_hash(ev: dict) -> tuple:
    p = ev.get("p_params", {})
    sy = tuple(ev.get("scale_data", {}).get("sY", {}).get("y", ()))
    rl = tuple(ev.get("raw_lines", ()))
    extra = ev.get("extra_params", [])
    apply_grain = extra[0] if extra else "1"
    return (
        apply_grain,
        p.get("ar_coeff_lag"),
        p.get("ar_coeff_shift"),
        p.get("grain_scale_shift"),
        p.get("scaling_shift"),
        sy,
        rl,
    )


def _get_timeline_max_workers() -> int:
    """Return bounded worker count configured for timeline multiprocessing."""
    num_cores = os.cpu_count() or 1
    default_workers = max(1, num_cores // 2)
    max_workers = get_setting("timeline_max_workers", default_workers)
    return max(1, min(int(max_workers), num_cores * 2))


def _mp_clipping_worker_task(task_args: tuple) -> tuple:
    """Top-level picklable worker computing AR grain extremes for a unique template."""
    (
        ext_key,
        seed,
        cy_tuple,
        cb_tuple,
        cr_tuple,
        ar_lag,
        ar_shift,
        gs_shift,
        is_444,
        needed_channels,
    ) = task_args
    from fgseditor_qt.math.fgs_grain_sim import compute_grain_extremes

    extremes = compute_grain_extremes(
        seed=seed,
        cy_coeffs=list(cy_tuple),
        cb_coeffs=list(cb_tuple),
        cr_coeffs=list(cr_tuple),
        ar_lag=ar_lag,
        ar_shift=ar_shift,
        grain_scale_shift=gs_shift,
        is_444=is_444,
        channels=needed_channels,
    )
    return ext_key, extremes


def _mp_worker_task(task_args: tuple) -> tuple:

    task_key, cy_tuple, ar_lag, ar_shift, gs_shift, sY_avg, scaling_shift = task_args
    from fgseditor_qt.math.fgs_grain_sim import compute_amplitude_at_point, get_luma_max_cached

    try:
        lmax = get_luma_max_cached(cy_tuple, ar_lag, ar_shift, gs_shift)
    except Exception:
        lmax = 0
    st = compute_amplitude_at_point(lmax, sY_avg, scaling_shift)
    return task_key, st


def _process_timeline_event(args):
    i, key, ev = args
    from fgseditor_qt.core import fgs_parser
    from fgseditor_qt.math.fgs_grain_sim import compute_amplitude_at_point, get_luma_max_cached

    if fgs_parser.get_apply_grain(ev) == 0:
        return i, key, 0.0

    scale_data = fgs_parser.get_scale_data(ev)
    sy_data = scale_data.get("sY", {})
    if not sy_data or not sy_data.get("y"):
        return i, key, 0.0

    evt_ctx = {"p_params": ev.get("p_params", fgs_parser.P_DEFAULTS)}
    ar_shift = fgs_parser.get_ar_coeff_shift(evt_ctx)
    ar_lag = fgs_parser.get_ar_coeff_lag(evt_ctx)
    scaling_shift = fgs_parser.get_scaling_shift(evt_ctx)
    gs_shift = fgs_parser.get_grain_scale_shift(evt_ctx)

    cy_coeffs, _, _ = fgs_parser.extract_ar_coeffs_from_raw_lines(
        ev.get("raw_lines", [])
    )

    try:
        lmax = get_luma_max_cached(tuple(cy_coeffs), ar_lag, ar_shift, gs_shift)
    except Exception:
        lmax = 0

    sY_avg = sum(sy_data["y"]) / len(sy_data["y"])
    strength = compute_amplitude_at_point(lmax, sY_avg, scaling_shift)

    return i, key, strength


class TimelineDataWorker(QThread):
    finished_data = Signal(object)
    progress = Signal(int)

    def __init__(self, missing_events):
        super().__init__()
        self.missing_events = missing_events
        self._is_cancelled = False
        self._executor = None

    def cancel(self):
        self._is_cancelled = True
        if self._executor is not None:
            try:
                self._executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

    def run(self):
        if not self.missing_events or self._is_cancelled:
            if not self._is_cancelled:
                self.progress.emit(100)
                self.finished_data.emit([])
            return

        import os
        import concurrent.futures
        from fgseditor_qt.core import fgs_parser
        from fgseditor_qt.core.settings_manager import get_setting

        self.progress.emit(5)

        unique_tasks = {}
        event_dispatch = []

        for i, key, ev in self.missing_events:
            if self._is_cancelled:
                return

            if fgs_parser.get_apply_grain(ev) == 0:
                event_dispatch.append((i, key, 0.0))
                continue

            scale_data = fgs_parser.get_scale_data(ev)
            sy_data = scale_data.get("sY", {})
            if not sy_data or not sy_data.get("y"):
                event_dispatch.append((i, key, 0.0))
                continue

            evt_ctx = {"p_params": ev.get("p_params", fgs_parser.P_DEFAULTS)}
            ar_shift = fgs_parser.get_ar_coeff_shift(evt_ctx)
            ar_lag = fgs_parser.get_ar_coeff_lag(evt_ctx)
            scaling_shift = fgs_parser.get_scaling_shift(evt_ctx)
            gs_shift = fgs_parser.get_grain_scale_shift(evt_ctx)

            cy_coeffs, _, _ = fgs_parser.extract_ar_coeffs_from_raw_lines(
                ev.get("raw_lines", [])
            )
            cy_tuple = tuple(cy_coeffs)
            sY_avg = sum(sy_data["y"]) / len(sy_data["y"])

            task_key = (cy_tuple, ar_lag, ar_shift, gs_shift, sY_avg, scaling_shift)
            event_dispatch.append((i, key, task_key))

            if task_key not in unique_tasks:
                unique_tasks[task_key] = (task_key, cy_tuple, ar_lag, ar_shift, gs_shift, sY_avg, scaling_shift)

        self.progress.emit(10)

        max_workers = _get_timeline_max_workers()

        tasks_list = list(unique_tasks.values())
        solved_cache = {}
        total_tasks = len(tasks_list)

        use_multiprocessing = total_tasks > 16 and max_workers > 1
        computed_successfully = False

        if use_multiprocessing and not self._is_cancelled:
            chunksize = max(8, total_tasks // (max_workers * 4))
            try:
                import multiprocessing

                mp_ctx = multiprocessing.get_context("spawn")
                self._executor = concurrent.futures.ProcessPoolExecutor(
                    max_workers=max_workers, mp_context=mp_ctx
                )
                for done_idx, (t_key, st) in enumerate(
                    self._executor.map(_mp_worker_task, tasks_list, chunksize=chunksize)
                ):
                    if self._is_cancelled:
                        return
                    solved_cache[t_key] = st
                    if done_idx % max(1, total_tasks // 80) == 0:
                        prog = 10 + int((done_idx + 1) / total_tasks * 85)
                        self.progress.emit(min(95, prog))
                computed_successfully = True
            except Exception:
                computed_successfully = False
            finally:
                if self._executor is not None:
                    try:
                        self._executor.shutdown(wait=False, cancel_futures=True)
                    except Exception:
                        pass
                    self._executor = None

        if not computed_successfully and not self._is_cancelled:
            for done_idx, task_args in enumerate(tasks_list):
                if self._is_cancelled:
                    return
                t_key, st = _mp_worker_task(task_args)
                solved_cache[t_key] = st
                if done_idx % max(1, total_tasks // 80) == 0:
                    prog = 10 + int((done_idx + 1) / total_tasks * 85)
                    self.progress.emit(min(95, prog))

        if self._is_cancelled:
            return

        results = []
        for i, original_key, target in event_dispatch:
            if isinstance(target, (int, float)):
                results.append((i, original_key, target))
            else:
                results.append((i, original_key, solved_cache.get(target, 0.0)))

        self.progress.emit(100)
        self.finished_data.emit(results)


def _clone_events(events: list[dict]) -> list[dict]:

    return [
        {
            k: (
                {
                    dk: (
                        {ik: (list(iv) if isinstance(iv, list) else iv) for ik, iv in dv.items()}
                        if isinstance(dv, dict)
                        else (list(dv) if isinstance(dv, list) else dv)
                    )
                    for dk, dv in v.items()
                }
                if isinstance(v, dict)
                else (list(v) if isinstance(v, list) else v)
            )
            for k, v in ev.items()
        }
        for ev in events
    ]


class FixClippingWorker(QThread):
    """Background worker fixing AR grain clipping across all timeline events."""

    progress = Signal(int)
    finished_fix = Signal(object)
    cancelled = Signal()
    error_occurred = Signal(str)

    def __init__(
        self,
        events: list[dict],
        bit_depth: int,
        v_info: dict,
        is_444: bool,
        fix_endpoints: bool = True,
    ):
        super().__init__()
        self.events = events
        self.bit_depth = bit_depth
        self.v_info = v_info
        self.is_444 = bool(is_444)
        self.fix_endpoints = bool(fix_endpoints)
        self._is_cancelled = False
        self._executor = None

    def cancel(self) -> None:
        self._is_cancelled = True
        executor = getattr(self, "_executor", None)
        if executor is not None:
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

    def run(self) -> None:
        try:
            from fgseditor_qt.core import fgs_parser
            from fgseditor_qt.math.fgs_grain_sim import (
                event_potentially_clipping_channels,
                fix_event_clipping,
                is_event_full_range,
            )

            total_events = len(self.events)
            if total_events == 0:
                self.progress.emit(100)
                self.finished_fix.emit((self.events, 0, 0))
                return

            last_pct = 0
            self.progress.emit(0)

            event_ext_keys: list[tuple | None] = [None] * total_events
            event_full_flags: list[bool] = [False] * total_events
            unique_specs: dict[tuple, tuple] = {}
            unique_channel_sets: dict[tuple, set[str]] = {}

            for idx, ev in enumerate(self.events):
                if self._is_cancelled:
                    self.cancelled.emit()
                    return

                is_full = is_event_full_range(ev, self.v_info)
                needed_channels = event_potentially_clipping_channels(
                    ev,
                    bit_depth=self.bit_depth,
                    is_full_range=is_full,
                    channels=("sY", "sCb", "sCr"),
                    fix_endpoints=self.fix_endpoints,
                )
                if not needed_channels:
                    continue

                p_params = fgs_parser.get_p_params(ev)
                lag = p_params.get("ar_coeff_lag", 3)
                ar_shift = p_params.get("ar_coeff_shift", 6)
                gs_shift = p_params.get("grain_scale_shift", 0)
                seed = fgs_parser.get_grain_seed(ev)
                cy, cb, cr = fgs_parser.extract_ar_coeffs_from_raw_lines(ev.get("raw_lines", []))

                cy_t = tuple(cy)
                cb_t = tuple(cb)
                cr_t = tuple(cr)
                ext_key = (seed, cy_t, cb_t, cr_t, lag, ar_shift, gs_shift, self.is_444)
                event_ext_keys[idx] = ext_key
                event_full_flags[idx] = is_full
                if ext_key not in unique_specs:
                    unique_specs[ext_key] = (
                        ext_key,
                        seed,
                        cy_t,
                        cb_t,
                        cr_t,
                        lag,
                        ar_shift,
                        gs_shift,
                        self.is_444,
                    )
                    unique_channel_sets[ext_key] = set(needed_channels)
                else:
                    unique_channel_sets[ext_key].update(needed_channels)

                if (idx & 1023) == 1023:
                    pct = int(5 * (idx + 1) / total_events)
                    if pct > last_pct:
                        last_pct = pct
                        self.progress.emit(pct)

            if not unique_specs:
                self.progress.emit(100)
                self.finished_fix.emit((self.events, 0, 0))
                return

            self.progress.emit(5)
            last_pct = 5

            max_workers = _get_timeline_max_workers()
            tasks_list = [
                spec + (tuple(c for c in ("sY", "sCb", "sCr") if c in unique_channel_sets[ext_key]),)
                for ext_key, spec in unique_specs.items()
            ]
            total_tasks = len(tasks_list)
            solved_cache: dict[tuple, dict[str, int]] = {}
            completed_tasks = 0

            def _emit_phase2_progress(done_count: int) -> None:
                nonlocal last_pct
                pct = 5 + int(80 * done_count / total_tasks)
                if pct > last_pct:
                    last_pct = pct
                    self.progress.emit(pct)

            use_multiprocessing = total_tasks > 16 and max_workers > 1
            if use_multiprocessing and not self._is_cancelled:
                chunksize = max(1, min(16, total_tasks // (max_workers * 4)))
                try:
                    import multiprocessing

                    mp_ctx = multiprocessing.get_context("spawn")
                    self._executor = concurrent.futures.ProcessPoolExecutor(
                        max_workers=max_workers, mp_context=mp_ctx
                    )
                    for ext_key, extremes in self._executor.map(
                        _mp_clipping_worker_task,
                        tasks_list,
                        chunksize=chunksize,
                    ):
                        if self._is_cancelled:
                            break
                        solved_cache[ext_key] = extremes
                        completed_tasks += 1
                        _emit_phase2_progress(completed_tasks)
                except Exception:
                    pass
                finally:
                    executor = self._executor
                    self._executor = None
                    if executor is not None:
                        try:
                            executor.shutdown(
                                wait=not self._is_cancelled,
                                cancel_futures=self._is_cancelled,
                            )
                        except Exception:
                            pass

            if self._is_cancelled:
                self.cancelled.emit()
                return

            if len(solved_cache) < total_tasks:
                for task_args in tasks_list:
                    if self._is_cancelled:
                        self.cancelled.emit()
                        return
                    ext_key = task_args[0]
                    if ext_key in solved_cache:
                        continue
                    _, extremes = _mp_clipping_worker_task(task_args)
                    solved_cache[ext_key] = extremes
                    completed_tasks += 1
                    _emit_phase2_progress(completed_tasks)

            modified_count = 0
            max_shift_overall = 0

            candidate_indices = [idx for idx, ext_key in enumerate(event_ext_keys) if ext_key is not None]
            total_candidates = len(candidate_indices)
            for c_idx, ev_idx in enumerate(candidate_indices):
                if self._is_cancelled:
                    self.cancelled.emit()
                    return
                ext_key = event_ext_keys[ev_idx]
                changed, max_shift = fix_event_clipping(
                    self.events[ev_idx],
                    bit_depth=self.bit_depth,
                    is_full_range=event_full_flags[ev_idx],
                    channels=("sY", "sCb", "sCr"),
                    is_444=self.is_444,
                    extremes=solved_cache.get(ext_key),
                    fix_endpoints=self.fix_endpoints,
                )
                if changed:
                    modified_count += 1
                    if max_shift > max_shift_overall:
                        max_shift_overall = max_shift

                pct = 85 + int(15 * (c_idx + 1) / total_candidates)
                if pct > last_pct:
                    last_pct = pct
                    self.progress.emit(pct)

            if self._is_cancelled:
                self.cancelled.emit()
                return

            self.progress.emit(100)
            self.finished_fix.emit((self.events, modified_count, max_shift_overall))
        except Exception as exc:
            if self._is_cancelled:
                self.cancelled.emit()
            else:
                self.error_occurred.emit(str(exc))


class DynamicTimelineUI(QWidget):
    def __init__(self, main_ui, file_data):
        super().__init__()
        self.main_ui = main_ui
        self.setWindowTitle("FGS Dynamic Timeline")
        self.setMinimumSize(900, 500)
        if not restore_window_geometry(self, "geometry_dynamic_timeline"):
            self.resize(1100, 650)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.file_data = file_data
        self.events = file_data["events"]
        self._clamp_last_event_to_video_duration()
        self._ensure_valid_master_chain()
        self.original_events = _clone_events(self.events)
        self.filepath = file_data["filepath"]
        self.header_lines = file_data["header_lines"]

        self.original_fps_text = DEFAULT_FPS_LABEL
        self._has_sanitization_changes = False
        self._is_temp = is_temp_filepath(self.filepath) or file_data.get("is_temp", False)


        undo_size = get_setting("undo_stack_size", 100)
        self._undo_stack = deque(maxlen=undo_size)
        self._redo_stack = deque(maxlen=undo_size)

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self._do_autosave)

        interval_min = get_setting("autosave_interval_minutes", 5)
        if interval_min > 0:
            self.autosave_timer.start(interval_min * 60000)

        self._wheel_undo_timer = QTimer(self)
        self._wheel_undo_timer.setSingleShot(True)
        self._wheel_undo_timer.timeout.connect(self._end_wheel_undo_gesture)
        self._wheel_gesture_active = False

        self._xlim_full: tuple[float, float] | None = None
        self._zoom_xlim: tuple[float, float] | None = None
        self._pan_active = False
        self._pan_start_x: float | None = None
        self._pan_xlim_start: tuple[float, float] | None = None

        self._select_active = False
        self._select_start_x: float | None = None
        self._select_overlay = None

        self._ev_t_start: list[float] = []
        self._ev_t_end: list[float] = []
        self._ev_strength: list[float] = []
        self._curve_line = None
        self._line_collection = None
        self._scatter_collection = None
        self._visible_indices: list[int] = []
        self._timeline_worker = None
        self._fix_clipping_worker = None
        self._save_apply_enabled_state = False

        win_title = "Unsaved FGS" if self._is_temp else os.path.basename(self.filepath)
        self.setWindowTitle(f"Dynamic FGS Timeline - {win_title}")
        self.setMinimumSize(500, 800)

        layout = QVBoxLayout(self)

        top_frame = QFrame()
        top_frame.setObjectName("toolbar")
        top_layout = QHBoxLayout(top_frame)

        self.close_btn = QPushButton("Close FGS")
        self.close_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.close_btn.clicked.connect(self.close)
        top_layout.addWidget(self.close_btn, stretch=0)

        display_file = "Unsaved FGS" if self._is_temp else self.filepath
        self.file_label = QLabel(f"File: {display_file}")
        self.file_label.setWordWrap(True)
        top_layout.addWidget(self.file_label, stretch=1)

        menu_bar = create_standard_menu(self)
        layout.setMenuBar(menu_bar)

        layout.addWidget(top_frame)

        mid_frame = QFrame()
        mid_frame.setObjectName("toolbar")
        mid_layout = QHBoxLayout(mid_frame)

        info_label = QLabel(f"{len(self.events)} event(s) detected")
        info_label.setStyleSheet("color: #4da6ff;")
        mid_layout.addWidget(info_label, stretch=1)

        fps_label = QLabel("FPS:")
        fps_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        mid_layout.addWidget(fps_label, stretch=0)

        self.fps_combo = QComboBox()
        self.fps_combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        default_fps = get_setting("default_fps", DEFAULT_FPS_LABEL)
        for lbl, _ in COMMON_FPS:
            self.fps_combo.addItem(lbl)
        self.fps_combo.setCurrentText(default_fps)
        self.fps_combo.setToolTip("Frame rate for timeline and frame conversions.")
        self.fps_combo.currentTextChanged.connect(self._on_fps_changed)
        mid_layout.addWidget(self.fps_combo, stretch=0)

        time_format_label = QLabel("Time Format:")
        time_format_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        mid_layout.addWidget(time_format_label, stretch=0)

        self.time_format_combo = QComboBox()
        self.time_format_combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.time_format_combo.addItems(["Seconds", "Frames", "Timestamp"])
        default_fmt = get_setting("default_time_format", "Frames")
        if default_fmt == "Timecode":
            default_fmt = "Timestamp"
        self.time_format_combo.setCurrentText(default_fmt)
        self.time_format_combo.setToolTip("Timeline display format.")
        self.time_format_combo.currentTextChanged.connect(self._on_time_format_changed)
        mid_layout.addWidget(self.time_format_combo, stretch=0)

        self.validation_warning_label = QLabel()

        self.validation_warning_label.setStyleSheet(
            "color: #ff4444; font-weight: bold; background: #220000; padding: 2px 6px; border-radius: 4px;"
        )
        self.validation_warning_label.hide()
        mid_layout.addWidget(self.validation_warning_label, stretch=0)

        self.save_btn = QPushButton("Save FGS")
        self.save_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.save_btn.clicked.connect(self.save_fgs)
        mid_layout.addWidget(self.save_btn, stretch=0)

        self.save_bin_btn = QPushButton("Save Binary")
        self.save_bin_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.save_bin_btn.clicked.connect(self.save_binary)
        mid_layout.addWidget(self.save_bin_btn, stretch=0)

        self.save_apply_btn = QPushButton("Save && Apply")
        self.save_apply_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.save_apply_btn.clicked.connect(self.save_and_apply)
        self.save_apply_btn.setEnabled(False)
        self.save_apply_btn.setVisible(False)
        mid_layout.addWidget(self.save_apply_btn, stretch=0)

        self.reset_zoom_btn = QPushButton("⟳ Reset Zoom")
        self.reset_zoom_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.reset_zoom_btn.setToolTip("Fit timeline to view.")
        self.reset_zoom_btn.clicked.connect(self.reset_zoom)
        mid_layout.addWidget(self.reset_zoom_btn, stretch=0)

        self.fix_clipping_btn = QPushButton("Fix clipping")
        self.fix_clipping_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.fix_clipping_btn.setToolTip("Shift points across all events and channels to prevent clipping")
        self.fix_clipping_btn.clicked.connect(self.fix_clipping_all_events)
        self.fix_clipping_btn.setEnabled(False)
        mid_layout.addWidget(self.fix_clipping_btn, stretch=0)

        self.save_plot_btn = QPushButton("Save Plot")
        self.save_plot_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.save_plot_btn.clicked.connect(self.save_plot_as_png)
        mid_layout.addWidget(self.save_plot_btn, stretch=0)

        layout.addWidget(mid_frame)

        te_container = QHBoxLayout()
        te_container.addStretch(1)

        self.time_edit_bar = QFrame()
        self.time_edit_bar.setStyleSheet(
            "background-color: #222222; border: 1px solid #4da6ff; border-radius: 4px;"
        )
        te_layout = QHBoxLayout(self.time_edit_bar)
        te_layout.setContentsMargins(8, 4, 8, 4)

        self.te_label = QLabel("Ev:")
        self.te_label.setStyleSheet(
            "color: white; font-weight: bold; border: none; background: transparent;"
        )
        te_layout.addWidget(self.te_label)

        l1 = QLabel("Start:")
        l1.setStyleSheet("color: white; background: transparent; border: none;")
        te_layout.addWidget(l1)
        self.te_start_input = QLineEdit()
        self.te_start_input.setMinimumWidth(110)
        self.te_start_input.setMaximumWidth(130)
        self.te_start_input.setStyleSheet("color: white; background: #111;")
        te_layout.addWidget(self.te_start_input)

        l2 = QLabel("End:")
        l2.setStyleSheet("color: white; background: transparent; border: none;")
        te_layout.addWidget(l2)
        self.te_end_input = QLineEdit()
        self.te_end_input.setMinimumWidth(110)
        self.te_end_input.setMaximumWidth(130)
        self.te_end_input.setStyleSheet("color: white; background: #111;")
        te_layout.addWidget(self.te_end_input)

        self.te_alter_neighbor = QCheckBox("Adjust neighbors")
        self.te_alter_neighbor.setStyleSheet(
            "color: white; border: none; background: transparent;"
        )
        te_layout.addWidget(self.te_alter_neighbor)

        self.te_close_btn = QPushButton("✕")
        self.te_close_btn.setFixedSize(20, 20)
        self.te_close_btn.setStyleSheet(
            "border: none; color: #ff4444; font-weight: bold; background: transparent;"
        )
        self.te_close_btn.clicked.connect(self._hide_time_edit_bar)
        te_layout.addWidget(self.te_close_btn)

        self.time_edit_bar.hide()
        te_container.addWidget(self.time_edit_bar)
        layout.addLayout(te_container)

        self.main_stack = QStackedWidget()
        layout.addWidget(self.main_stack, stretch=1)

        self.figure = Figure(figsize=(10, 3), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.figure.patch.set_facecolor("#1e1e1e")
        self.ax.set_facecolor("#111111")
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setStyleSheet("background-color: #1e1e1e;")
        self.main_stack.addWidget(self.canvas)

        self._editing_event_idx = -1
        self.te_start_input.editingFinished.connect(
            lambda: self._on_inline_editing_finished(True)
        )
        self.te_end_input.editingFinished.connect(
            lambda: self._on_inline_editing_finished(False)
        )

        self.te_start_input.installEventFilter(self)
        self.te_end_input.installEventFilter(self)

        self.progress_container = QWidget()
        self.progress_container.setStyleSheet("background-color: #1e1e1e;")
        prog_layout = QVBoxLayout(self.progress_container)
        prog_layout.setAlignment(Qt.AlignCenter)
        self.progress_label = QLabel("Calculating timeline data...")
        self.progress_label.setStyleSheet("color: white; font-size: 14px;")
        self.progress_label.setAlignment(Qt.AlignCenter)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setMinimumWidth(300)
        self.progress_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #444; border-radius: 5px; text-align: center; color: white; }"
            "QProgressBar::chunk { background-color: #4da6ff; width: 20px; }"
        )
        self.progress_cancel_btn = QPushButton("Cancel")
        self.progress_cancel_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.progress_cancel_btn.clicked.connect(self._cancel_fix_clipping)
        self.progress_cancel_btn.hide()
        prog_layout.addWidget(self.progress_label)
        prog_layout.addWidget(self.progress_bar)
        prog_layout.addWidget(self.progress_cancel_btn, alignment=Qt.AlignCenter)
        self.main_stack.addWidget(self.progress_container)

        self.build_timeline()
        self.canvas.mpl_connect("pick_event", self.on_pick)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_mouse_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_mouse_move)
        self.canvas.mpl_connect("button_release_event", self._on_mouse_release)
        self.canvas.mpl_connect("axes_leave_event", self._on_mouse_leave)
        self.setAcceptDrops(True)
        self._update_ui_state()

        if getattr(self.main_ui, "_video_path", None):
            self._update_save_apply_state()
            fname = os.path.basename(self.main_ui._video_path)
            self.file_label.setText(f"File: {self.filepath} | Video: {fname}")

    def set_has_sanitization_changes(self, changed: bool):
        self._has_sanitization_changes = changed
        self._update_ui_state()

    def is_dirty(self) -> bool:
        if getattr(self, "_has_sanitization_changes", False):
            return True
        if getattr(self, "_is_temp", False) or not self.filepath or is_temp_filepath(self.filepath):
            return True
        if self.events != self.original_events:
            return True
        if self.fps_combo.currentText() != self.original_fps_text:
            return True
        return False

    def _get_validation_errors(self) -> list[str]:
        all_errors = []

        for idx, ev in enumerate(self.events):
            if fgs_parser.get_apply_grain(ev) == 0:
                continue

            ar_shift = fgs_parser.get_ar_coeff_shift(ev)

            cy_coeffs, cb_coeffs, cr_coeffs = (
                fgs_parser.extract_ar_coeffs_from_raw_lines(ev.get("raw_lines", []))
            )

            ev_has_errors = False
            for ch, coeffs, ch_key in [
                ("Y", cy_coeffs, "sY"),
                ("Cb", cb_coeffs, "sCb"),
                ("Cr", cr_coeffs, "sCr"),
            ]:
                if ch == "Y":
                    ys = fgs_parser.get_sY_values(ev)
                elif ch == "Cb":
                    ys = fgs_parser.get_sCb_values(ev)
                else:
                    ys = fgs_parser.get_sCr_values(ev)

                errors = fgs_math.validate_fgs_pipeline(coeffs, ar_shift, ys)
                if errors:
                    if not ev_has_errors:
                        all_errors.append(f"Event {idx + 1}:")
                        ev_has_errors = True
                    all_errors.append(
                        "\n".join(f" - Channel {ch}: {e}" for e in errors)
                    )

        return all_errors

    def _is_clipping_busy(self) -> bool:
        worker = getattr(self, "_fix_clipping_worker", None)
        return worker is not None and worker.isRunning()

    def _is_timeline_busy(self) -> bool:
        worker = getattr(self, "_timeline_worker", None)
        return worker is not None and worker.isRunning()

    def _apply_toolbar_busy_state(self, fix_busy: bool, timeline_busy: bool) -> None:
        can_save = bool(self.events) and not fix_busy
        self.save_btn.setEnabled(can_save)
        if hasattr(self, "save_bin_btn"):
            self.save_bin_btn.setEnabled(can_save)
        if hasattr(self, "save_apply_btn"):
            self.save_apply_btn.setEnabled(
                getattr(self, "_save_apply_enabled_state", False) and not fix_busy
            )
        if hasattr(self, "fix_clipping_btn"):
            self.fix_clipping_btn.setEnabled(
                bool(self.events) and not fix_busy and not timeline_busy
            )
        for ctrl_name in ("fps_combo", "time_format_combo", "reset_zoom_btn", "save_plot_btn"):
            ctrl = getattr(self, ctrl_name, None)
            if ctrl is not None:
                ctrl.setEnabled(not fix_busy)

    def _update_ui_state(self):
        dirty = self.is_dirty()

        errors = self._get_validation_errors()
        if errors:
            self.validation_warning_label.setText("⚠ UNSAFE SETTINGS")
            self.validation_warning_label.setToolTip("\n\n".join(errors))
            self.validation_warning_label.show()
        else:
            self.validation_warning_label.hide()

        self._apply_toolbar_busy_state(
            fix_busy=self._is_clipping_busy(),
            timeline_busy=self._is_timeline_busy(),
        )

        fname = "Unsaved FGS" if (getattr(self, "_is_temp", False) or not self.filepath or is_temp_filepath(self.filepath)) else os.path.basename(self.filepath)
        title = f"Dynamic FGS Timeline - {fname}"
        if dirty:
            title += " *"
        self.setWindowTitle(title)

    def _on_fps_changed(self, text: str):
        if self._is_clipping_busy():
            return
        self._update_ui_state()
        if self.time_format_combo.currentText() == "Frames":
            self.build_timeline()
        self._update_inline_edit_bar_text()

    def _on_time_format_changed(self, text: str):
        if self._is_clipping_busy():
            return
        self.build_timeline()
        self._update_inline_edit_bar_text()

    def closeEvent(self, event):
        if getattr(self, "editor", None) is not None:
            if not self.editor.close():
                event.ignore()
                return

        if self.is_dirty():
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "Save changes before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Save:
                if self.save_fgs():
                    event.accept()
                else:
                    event.ignore()
                    return
            elif reply == QMessageBox.Discard:
                event.accept()
            else:
                event.ignore()
                return

        for worker_attr, signal_names in (
            ("_timeline_worker", ("finished_data", "progress")),
            ("_fix_clipping_worker", ("finished_fix", "cancelled", "error_occurred", "progress")),
        ):
            worker = getattr(self, worker_attr, None)
            if worker is not None:
                for sig_name in signal_names:
                    sig = getattr(worker, sig_name, None)
                    if sig is not None:
                        try:
                            sig.disconnect()
                        except Exception:
                            pass
                if worker.isRunning():
                    worker.cancel()
                    worker.wait(3000)

        if self.figure:
            import matplotlib.pyplot as plt

            plt.close(self.figure)
        if self.canvas:
            self.canvas.deleteLater()

        self.figure = None
        self.canvas = None
        self.ax = None
        self.lines = []
        self._curve_line = None
        self._line_collection = None
        self._scatter_collection = None
        self._select_overlay = None
        self._undo_stack.clear()
        self._redo_stack.clear()

        self.main_ui.filepath = None
        self.main_ui._current_event = None
        self.main_ui._video_path = None
        self.main_ui._video_info = None
        self.main_ui.editor.close_plotters()
        self.main_ui.editor.load_event(None)
        self.main_ui.editor.set_video_info(None)
        self.main_ui.editor.set_save_apply_enabled(False)
        self.main_ui.dynamic_ui = None
        self.main_ui.stacked_widget.setCurrentIndex(0)
        self.main_ui.setWindowTitle("FGSEditor")

        if self.autosave_timer.isActive():
            self.autosave_timer.stop()

        save_window_geometry(self, "geometry_dynamic_timeline")
        self.main_ui.show()
        super().closeEvent(event)

    def _do_autosave(self):
        if not self.is_dirty() or not self.events:
            return

        backup_dir = os.path.join(get_user_data_dir(), "backup")
        try:
            os.makedirs(backup_dir, exist_ok=True)
        except OSError:
            return

        is_static = len(self.events) <= 1

        mode_str = "static" if is_static else "dynamic"
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")

        if self.filepath and os.path.basename(self.filepath) != "Untitled":
            base_name = os.path.splitext(os.path.basename(self.filepath))[0]
        else:
            base_name = "Untitled"

        backup_filename = f"{base_name}_{timestamp}_{mode_str}.txt"
        backup_path = os.path.join(backup_dir, backup_filename)

        from fgseditor_qt.core.fgs_save import build_dynamic_lines

        try:
            lines = build_dynamic_lines(self.header_lines, self.events)
            with open(backup_path, "w", encoding="utf-8", newline="\n") as f:
                f.writelines(lines)
        except Exception:
            pass

    def _push_undo(self):
        self._undo_stack.append(_clone_events(self.events))
        self._redo_stack.clear()
        self._update_ui_state()

    def undo(self):
        if self._is_clipping_busy() or not self._undo_stack:
            return
        self._redo_stack.append(_clone_events(self.events))
        self.events = self._undo_stack.pop()
        self.build_timeline()
        self._update_ui_state()

    def redo(self):
        if self._is_clipping_busy() or not self._redo_stack:
            return
        self._undo_stack.append(_clone_events(self.events))
        self.events = self._redo_stack.pop()
        self.build_timeline()
        self._update_ui_state()

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.ControlModifier:
            if event.key() == Qt.Key_Z:
                self.undo()
                return
            if event.key() == Qt.Key_Y:
                self.redo()
                return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if self._is_clipping_busy():
            return
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            filepath = urls[0].toLocalFile()
            event.acceptProposedAction()
            ext = os.path.splitext(filepath)[1].lower()
            if ext in (
                ".mkv",
                ".ivf",
                ".hevc",
                ".avi",
                ".mov",
                ".webm",
                ".ts",
                ".flv",
                ".mp4",
            ):
                def _handle_dropped_video(p):
                    self.main_ui._video_path = p
                    from fgseditor_qt.tools.video_probe import probe_video
                    try:
                        self.main_ui._video_info = probe_video(p)
                    except Exception:
                        self.main_ui._video_info = {}
                    self._clamp_last_event_to_video_duration()
                    self._update_save_apply_state()
                    fname = os.path.basename(p)
                    self.file_label.setText(f"File: {self.filepath} | Video: {fname}")
                    self.build_timeline()

                QTimer.singleShot(0, lambda: _handle_dropped_video(filepath))

    def _clamp_last_event_to_video_duration(self) -> None:
        video_info = getattr(self.main_ui, "_video_info", None)
        if not video_info or not self.events:
            return
        from fgseditor_qt.math.time_utils import video_info_to_ticks
        vid_ticks = video_info_to_ticks(video_info)
        if vid_ticks <= 0:
            return

        trimmed = [ev for ev in self.events if ev.get("start_time", 0) < vid_ticks]
        if trimmed:
            changed = len(trimmed) != len(self.events)
            for ev in trimmed:
                if ev.get("end_time", 0) > vid_ticks:
                    ev["end_time"] = vid_ticks
                    params_str = " ".join(ev.get("extra_params", ["1", "7391", "1"]))
                    ev["e_line"] = f"E {ev['start_time']} {ev['end_time']} {params_str}\n"
                    changed = True
            if changed:
                self.events = trimmed
                self._has_sanitization_changes = True
        elif self.events:
            ev = self.events[0]
            ev["start_time"] = 0
            ev["end_time"] = vid_ticks
            params_str = " ".join(ev.get("extra_params", ["1", "7391", "1"]))
            ev["e_line"] = f"E {ev['start_time']} {ev['end_time']} {params_str}\n"
            self.events = [ev]
            self._has_sanitization_changes = True

    _COLORS = [
        "#4ade80",
        "#60a5fa",
        "#f87171",
        "#fbbf24",
        "#c084fc",
        "#f472b6",
        "#2dd4bf",
        "#a78bfa",
    ]

    def build_timeline(self):
        if self._is_clipping_busy():
            return
        self._clamp_last_event_to_video_duration()
        self._ensure_valid_master_chain()
        self.lines = []
        self._curve_line = None
        self._line_collection = None
        self._scatter_collection = None
        self.ax.clear()
        self.ax.set_facecolor("#111111")

        if not self.events:
            self.canvas.draw_idle()
            return

        if not hasattr(self, "_strength_cache"):
            self._strength_cache = {}

        missing_events = []
        for i, ev in enumerate(self.events):
            key = _get_event_hash(ev)
            if key not in self._strength_cache:
                missing_events.append((i, key, ev))

        if missing_events:
            self.progress_label.setText("Calculating timeline data...")
            self.progress_cancel_btn.hide()
            if hasattr(self, "fix_clipping_btn"):
                self.fix_clipping_btn.setEnabled(False)
            self.progress_bar.setValue(0)
            self.main_stack.setCurrentWidget(self.progress_container)
            from PySide6.QtWidgets import QApplication

            QApplication.processEvents()

            if hasattr(self, "_timeline_worker") and self._timeline_worker is not None and self._timeline_worker.isRunning():
                try:
                    self._timeline_worker.finished_data.disconnect()
                    self._timeline_worker.progress.disconnect()
                except Exception:
                    pass
                self._timeline_worker.cancel()
                self._timeline_worker.wait(3000)

            self._timeline_worker = TimelineDataWorker(missing_events)
            self._timeline_worker.progress.connect(self.progress_bar.setValue)
            self._timeline_worker.finished_data.connect(self._on_timeline_data_ready)
            self._timeline_worker.start()
        else:
            self._on_timeline_data_ready([])

    def _on_timeline_data_ready(self, new_results):
        if self.canvas is None or self.ax is None:
            return
        self.main_stack.setCurrentWidget(self.canvas)
        if hasattr(self, "fix_clipping_btn"):
            self.fix_clipping_btn.setEnabled(bool(self.events) and not self._is_clipping_busy())
        if not hasattr(self, "_strength_cache"):
            self._strength_cache = {}

        for idx, key, strength in new_results:
            self._strength_cache[key] = strength

        n = len(self.events)
        import numpy as np

        t_starts = np.empty(n)
        t_ends = np.empty(n)
        strengths = np.empty(n)

        from fgseditor_qt.math.time_utils import ticks_to_seconds

        for i, ev in enumerate(self.events):
            t_starts[i] = ticks_to_seconds(ev["start_time"])
            t_ends[i] = ticks_to_seconds(ev["end_time"])
            key = _get_event_hash(ev)
            strengths[i] = self._strength_cache.get(key, 0.0)

        colors_cycle = self._COLORS
        self._ev_t_start = t_starts.tolist()
        self._ev_t_end = t_ends.tolist()
        self._ev_strength = strengths.tolist()
        self._ev_mid_x = ((t_starts + t_ends) / 2.0).tolist()
        self._label_artists = []
        self._visible_indices = []

        min_s = float(strengths.min()) if n > 0 else 0.0
        max_s = float(strengths.max()) if n > 0 else 0.0
        min_t = float(t_starts.min()) if n > 0 else 0.0
        max_t = float(t_ends.max()) if n > 0 else 0.0

        t_span = max(1e-4, max_t - min_t)

        offset_x = max(1e-4, t_span * 0.008)
        full_xmin = -offset_x if min_t <= offset_x else (min_t - offset_x)
        full_xmax = max_t + max(1e-4, t_span * 0.02)
        self._xlim_full = (full_xmin, full_xmax)

        margin_y_top = max(5.0, (max_s - min_s) * 0.3)
        self._margin_y = margin_y_top

        offset_y = max(0.1, max_s * 0.035)
        ymin = -offset_y if min_s <= offset_y else max(0.0, min_s - offset_y)
        ymax = max_s + margin_y_top * 1.2
        self._ylim_bounds = (ymin, ymax)

        # Precompute per-event segment colors
        seg_colors = []
        for i, ev in enumerate(self.events):
            extra = ev.get("extra_params") or ["1", "7391", "1"]
            try:
                ag = int(extra[0]) if len(extra) > 0 else 1
                up = int(extra[2]) if len(extra) > 2 else 1
            except (ValueError, TypeError):
                ag, up = 1, 1

            if ag == 0:
                seg_colors.append("#ff4444")
            elif up == 0:
                seg_colors.append("#38bdf8")
            else:
                seg_colors.append(colors_cycle[i % len(colors_cycle)])
        self._ev_colors = seg_colors

        t_curve = np.empty(2 * n)
        s_curve = np.empty(2 * n)
        t_curve[0::2] = t_starts
        t_curve[1::2] = t_ends
        s_curve[0::2] = strengths
        s_curve[1::2] = strengths
        (self._curve_line,) = self.ax.plot(
            t_curve,
            s_curve,
            color="#38bdf8",
            linewidth=1.5,
            zorder=2,
            clip_on=True,
            visible=False,
        )

        lc = LineCollection(
            [],
            linewidths=4,
            capstyle="butt",
            picker=12,
            clip_on=True,
            zorder=2,
        )
        self.ax.add_collection(lc)
        self._line_collection = lc

        sc = self.ax.scatter(
            [],
            [],
            s=70,
            zorder=3,
            clip_on=True,
            picker=12,
            edgecolors="white",
            linewidths=1,
            alpha=0.9,
            visible=False,
        )
        self._scatter_collection = sc

        self.ax.set_title("Timeline Overview (Click to select, double-click event to edit)", color="white")

        time_format = self.time_format_combo.currentText()
        fps = fps_from_label(self.fps_combo.currentText())

        if time_format == "Frames":
            self.ax.set_xlabel("Time (frames)", color="#cccccc")

            def frame_formatter(x, pos):
                if x < -1e-6:
                    return ""
                frames = ticks_to_frames(seconds_to_ticks(x), fps)
                return str(frames)

            self.ax.xaxis.set_major_formatter(FuncFormatter(frame_formatter))
        elif time_format == "Timestamp":
            self.ax.set_xlabel("Time (HH:MM:SS:mmm)", color="#cccccc")

            def timecode_formatter(x, pos):
                if x < -1e-6:
                    return ""
                ticks = seconds_to_ticks(x)
                return ticks_to_timecode(ticks)

            self.ax.xaxis.set_major_formatter(FuncFormatter(timecode_formatter))
        else:
            self.ax.set_xlabel("Time (seconds)", color="#cccccc")

            def sec_formatter(x, pos):
                if x < -1e-6:
                    return ""
                return f"{x:.2f}"

            self.ax.xaxis.set_major_formatter(FuncFormatter(sec_formatter))

        self.ax.xaxis.set_major_locator(NonNegativeLocator(nbins=8))

        self.ax.set_ylabel("Effective Amplitude (px \u00b1)", color="#cccccc")
        self.ax.tick_params(colors="white")

        self.ax.yaxis.set_major_locator(NonNegativeLocator(nbins=6, integer=True))

        def amplitude_formatter(y, pos):
            if y < -1e-6:
                return ""
            return f"{int(round(y))}"

        self.ax.yaxis.set_major_formatter(FuncFormatter(amplitude_formatter))

        if self._zoom_xlim:
            self.ax.set_xlim(*self._zoom_xlim)
        else:
            self.ax.set_xlim(*self._xlim_full)

        self.ax.set_ylim(*self._ylim_bounds)
        self.ax.grid(True, linestyle="--", color="#444444", alpha=0.3)

        self.figure.tight_layout()
        self._update_view()
        self.canvas.draw_idle()

    def _find_event_at_x(self, xdata: float) -> int | None:
        if xdata is None or not getattr(self, "_ev_t_start", None):
            return None
        import bisect
        n_ev = len(self._ev_t_start)
        pos = bisect.bisect_right(self._ev_t_start, xdata) - 1
        if 0 <= pos < n_ev:
            is_last_or_gap = (pos == n_ev - 1) or (self._ev_t_end[pos] < self._ev_t_start[pos + 1])
            if is_last_or_gap:
                if self._ev_t_start[pos] <= xdata <= self._ev_t_end[pos]:
                    return pos
            else:
                if self._ev_t_start[pos] <= xdata < self._ev_t_end[pos]:
                    return pos
        if 0 <= pos + 1 < n_ev:
            if self._ev_t_start[pos + 1] <= xdata <= self._ev_t_end[pos + 1]:
                return pos + 1
        candidates = [p for p in (pos, pos + 1) if 0 <= p < len(self._ev_t_start)]
        if candidates and hasattr(self, "ax") and self.ax is not None:
            best_p = min(
                candidates,
                key=lambda p: min(
                    abs(xdata - self._ev_t_start[p]),
                    abs(xdata - self._ev_t_end[p]),
                ),
            )
            bbox = self.ax.get_window_extent()
            cur_xlim = self.ax.get_xlim()
            cur_range = cur_xlim[1] - cur_xlim[0]
            if cur_range > 0 and bbox.width > 0:
                dt = min(
                    abs(xdata - self._ev_t_start[best_p]),
                    abs(xdata - self._ev_t_end[best_p]),
                )
                px_dist = dt * (bbox.width / cur_range)
                if px_dist < 15:
                    return best_p
        return None

    def _clear_labels(self):
        for artist in getattr(self, "_label_artists", []):
            try:
                artist.remove()
            except Exception:
                pass
        self._label_artists = []

    def _render_labels(self, visible_indices: list[int]):
        self._clear_labels()
        margin_y = getattr(self, "_margin_y", 5)
        font_size = max(6, min(10, 10 - len(visible_indices) // 50))
        colors_cycle = self._COLORS

        for i in visible_indices:
            color = (
                self._ev_colors[i]
                if getattr(self, "_ev_colors", None) and i < len(self._ev_colors)
                else colors_cycle[i % len(colors_cycle)]
            )
            ev = self.events[i]
            extra = ev.get("extra_params") or ["1", "7391", "1"]
            try:
                ag = int(extra[0]) if len(extra) > 0 else 1
                up = int(extra[2]) if len(extra) > 2 else 1
            except (ValueError, TypeError):
                ag, up = 1, 1

            label_text = f"E{i + 1}"
            edge_color = color
            bg_color = "#222222"
            text_color = color

            if ag == 0:
                label_text = f"⚠ E{i + 1} (OFF)"
                edge_color = "#ff4444"
                text_color = "#ff6666"
                bg_color = "#2a1515"
            elif up == 0:
                master_idx = fgs_parser.find_master_event_idx(self.events, i)
                if master_idx is not None:
                    label_text = f"E{i + 1} ↳ E{master_idx + 1}"
                else:
                    label_text = f"E{i + 1} ↳ ?"
                edge_color = "#4da6ff"
                text_color = "#80c1ff"
                bg_color = "#15202b"

            txt = self.ax.text(
                self._ev_mid_x[i],
                self._ev_strength[i] + margin_y * 0.2,
                label_text,
                color=text_color,
                ha="center",
                va="bottom",
                fontsize=font_size,
                fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", fc=bg_color, ec=edge_color, alpha=0.9),
                clip_on=True,
            )
            self._label_artists.append(txt)

    def _update_view(self):
        if not getattr(self, "_ev_t_start", None) or self.ax is None:
            return

        xmin, xmax = self.ax.get_xlim()
        import bisect
        import numpy as np

        left_idx = max(0, bisect.bisect_right(self._ev_t_end, xmin) - 1)
        right_idx = min(len(self._ev_t_start), bisect.bisect_right(self._ev_t_start, xmax) + 1)
        n_span = right_idx - left_idx

        if n_span > 1000:
            if hasattr(self, "_curve_line") and self._curve_line is not None:
                self._curve_line.set_visible(True)
            if hasattr(self, "_line_collection") and self._line_collection is not None:
                self._line_collection.set_visible(False)
            if hasattr(self, "_scatter_collection") and self._scatter_collection is not None:
                self._scatter_collection.set_visible(False)
            self._clear_labels()
            self._visible_indices = []
            return

        if hasattr(self, "_curve_line") and self._curve_line is not None:
            self._curve_line.set_visible(False)

        visible_indices = [
            i
            for i in range(left_idx, right_idx)
            if self._ev_t_end[i] >= xmin and self._ev_t_start[i] <= xmax
        ]
        self._visible_indices = visible_indices

        if not visible_indices:
            if hasattr(self, "_line_collection") and self._line_collection is not None:
                self._line_collection.set_visible(False)
            if hasattr(self, "_scatter_collection") and self._scatter_collection is not None:
                self._scatter_collection.set_visible(False)
            self._clear_labels()
            return

        bbox = self.ax.get_window_extent()
        px_width = bbox.width if bbox.width > 0 else 800.0
        cur_range = xmax - xmin
        data_per_px = cur_range / px_width if px_width > 0 else 0.001
        min_half_w = data_per_px * 1.5

        vis_segs = []
        vis_colors = []
        n_total = len(self._ev_t_start)
        for i in visible_indices:
            s_i = self._ev_t_start[i]
            e_i = self._ev_t_end[i]
            y_i = self._ev_strength[i]
            if (e_i - s_i) < 2 * min_half_w:
                m = (s_i + e_i) / 2.0
                s_i = m - min_half_w
                e_i = m + min_half_w
                if i > 0 and s_i < self._ev_t_end[i - 1]:
                    s_i = self._ev_t_end[i - 1]
                if i < n_total - 1 and e_i > self._ev_t_start[i + 1]:
                    e_i = self._ev_t_start[i + 1]
            vis_gap = min((e_i - s_i) * 0.2, data_per_px * 1.0)
            if vis_gap > 0:
                if i > 0 and self._ev_t_start[i] <= self._ev_t_end[i - 1] + 1e-9:
                    s_i += vis_gap
                if i < n_total - 1 and self._ev_t_end[i] >= self._ev_t_start[i + 1] - 1e-9:
                    e_i -= vis_gap
            vis_segs.append([(s_i, y_i), (e_i, y_i)])
            vis_colors.append(self._ev_colors[i])

        if hasattr(self, "_line_collection") and self._line_collection is not None:
            self._line_collection.set_segments(vis_segs)
            self._line_collection.set_colors(vis_colors)
            self._line_collection.set_visible(True)

        if len(visible_indices) <= 200 and hasattr(self, "_scatter_collection") and self._scatter_collection is not None:
            vis_mids = [self._ev_mid_x[i] for i in visible_indices]
            vis_strengths = [self._ev_strength[i] for i in visible_indices]
            offsets = np.column_stack([vis_mids, vis_strengths])
            self._scatter_collection.set_offsets(offsets)
            self._scatter_collection.set_color(vis_colors)
            self._scatter_collection.set_visible(True)
        else:
            if hasattr(self, "_scatter_collection") and self._scatter_collection is not None:
                self._scatter_collection.set_visible(False)

        if len(visible_indices) < _MAX_LABELS:
            self._render_labels(visible_indices)
        else:
            self._clear_labels()

    def _update_labels(self):
        self._update_view()

    def on_pick(self, event):
        if event.mouseevent is None or self._pan_active:
            return
        idx = None
        if hasattr(event.mouseevent, "xdata") and event.mouseevent.xdata is not None:
            idx = self._find_event_at_x(event.mouseevent.xdata)
        if idx is None and len(event.ind) > 0:
            local_idx = int(event.ind[0])
            if hasattr(self, "_visible_indices") and self._visible_indices and 0 <= local_idx < len(self._visible_indices):
                idx = self._visible_indices[local_idx]
            elif 0 <= local_idx < len(self.events):
                idx = local_idx

        if idx is not None and event.mouseevent.button == 1:
            self._show_time_edit_bar(idx)

    def _confirm_delete(self, idx: int) -> bool:
        reply = QMessageBox.question(
            self,
            "Delete Event",
            f"Are you sure you want to delete Event {idx + 1}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _show_context_menu(self, idx, xdata):
        self._show_event_context_menu(idx, xdata)

    def _show_empty_space_context_menu(self, xdata):
        menu = QMenu(self)
        action_add = menu.addAction("Add Event Here")
        action_reset = menu.addAction("Reset Zoom")

        action = menu.exec(QCursor.pos())
        if action is None:
            return

        def trigger_action():
            if action == action_add:
                self._add_event_at_position(xdata)
            elif action == action_reset:
                self.reset_zoom()

        QTimer.singleShot(50, trigger_action)

    def _show_event_context_menu(self, idx, xdata):
        menu = QMenu(self)
        action_edit = menu.addAction("Edit Event")
        action_dur = menu.addAction("Edit Time Bounds")
        menu.addSeparator()

        action_add = menu.addAction("Add Event After")

        menu.addSeparator()
        del_menu = menu.addMenu("Delete")
        action_del_simple = del_menu.addAction("Delete")
        action_del_align = del_menu.addAction("Delete and Fill Gap")
        action_del_interp = del_menu.addAction("Delete and Interpolate")

        if idx == 0 or idx == len(self.events) - 1:
            action_del_interp.setEnabled(False)

        action = menu.exec(QCursor.pos())
        if action is None:
            return

        def trigger_action():
            if action == action_edit:
                self.open_editor(idx)
            elif action == action_dur:
                self.edit_time_bounds(idx)
            elif action == action_add:
                self._add_event_after_event(idx)
            elif action == action_del_simple:
                self._delete_event_simple(idx)
            elif action == action_del_align:
                self._delete_event_align(idx)
            elif action == action_del_interp:
                self._delete_event_interpolate(idx)

        QTimer.singleShot(50, trigger_action)

    def _delete_event_simple(self, idx):
        if not self._confirm_delete(idx):
            return
        self._push_undo()
        self.events.pop(idx)
        self._ensure_valid_master_chain()
        self.build_timeline()
        self._update_ui_state()

    @staticmethod
    def _sync_event_e_line(ev: dict) -> None:
        params_str = " ".join(ev.get("extra_params") or ["1", "7391", "1"])
        ev["e_line"] = f"E {ev['start_time']} {ev['end_time']} {params_str}\n"

    def _ensure_valid_master_chain(self) -> None:
        have_model = False
        master_ev = None
        for ev in self.events:
            extra = list(ev.get("extra_params") or ["1", "7391", "1"])
            if len(extra) < 3:
                defaults = ["1", "7391", "1"]
                extra.extend(defaults[len(extra) : 3])
            ag = extra[0] != "0"
            up = extra[2] != "0"
            if not ag:
                if up:
                    extra[2] = "0"
                    ev["extra_params"] = extra
                    self._sync_event_e_line(ev)
            else:
                if not up and not have_model:
                    extra[2] = "1"
                    ev["extra_params"] = extra
                    self._sync_event_e_line(ev)
                    have_model = True
                    master_ev = ev
                elif up:
                    have_model = True
                    master_ev = ev
                elif master_ev is not None:
                    if "scale_data" in master_ev and master_ev["scale_data"] is not None:
                        ev["scale_data"] = copy.deepcopy(master_ev["scale_data"])
                    if "p_params" in master_ev and master_ev["p_params"] is not None:
                        ev["p_params"] = copy.deepcopy(master_ev["p_params"])
                    if "raw_lines" in master_ev and master_ev["raw_lines"] is not None:
                        ev["raw_lines"] = list(master_ev["raw_lines"])

    def _delete_event_align(self, idx):
        if not self._confirm_delete(idx):
            return
        self._push_undo()
        ev = self.events[idx]
        t_start = ev["start_time"]
        t_end = ev["end_time"]

        has_prev = idx > 0
        has_next = idx < len(self.events) - 1

        self.events.pop(idx)

        if has_prev and has_next:
            fps = self._current_fps()
            mid_raw = (t_start + t_end) // 2
            if fps > 0:
                mid_f = ticks_to_frames(mid_raw, fps)
                prev_start_f = ticks_to_frames(self.events[idx - 1]["start_time"], fps)
                next_end_f = ticks_to_frames(self.events[idx]["end_time"], fps)
                mid_f = max(prev_start_f + 1, min(max(prev_start_f + 1, next_end_f - 1), mid_f))
                mid_t = frames_to_ticks(mid_f, fps)
            else:
                mid_t = mid_raw
            mid_t = max(
                self.events[idx - 1]["start_time"] + 1,
                min(self.events[idx]["end_time"] - 1, mid_t),
            )
            self.events[idx - 1]["end_time"] = mid_t
            self.events[idx]["start_time"] = mid_t
            self._sync_event_e_line(self.events[idx - 1])
            self._sync_event_e_line(self.events[idx])
        elif has_prev:
            self.events[idx - 1]["end_time"] = t_end
            self._sync_event_e_line(self.events[idx - 1])
        elif has_next:
            self.events[idx]["start_time"] = t_start
            self._sync_event_e_line(self.events[idx])

        self._ensure_valid_master_chain()
        self.build_timeline()
        self._update_ui_state()

    def _delete_event_interpolate(self, idx):
        has_prev = idx > 0
        has_next = idx < len(self.events) - 1
        if not (has_prev and has_next):
            return

        if not self._confirm_delete(idx):
            return

        self._push_undo()
        ev_L = self.events[idx - 1]
        ev_R = self.events[idx + 1]
        target_start = self.events[idx]["start_time"]
        target_end = self.events[idx]["end_time"]

        import math
        from fgseditor_qt.core import fgs_parser
        from fgseditor_qt.core.fgs_save import _build_p_line, _build_scale_line

        p_L = fgs_parser.get_p_params(ev_L)
        p_R = fgs_parser.get_p_params(ev_R)
        new_p = {}
        for k in fgs_parser.P_DEFAULTS:
            v_L = p_L.get(k, fgs_parser.P_DEFAULTS[k])
            v_R = p_R.get(k, fgs_parser.P_DEFAULTS[k])
            new_p[k] = math.ceil((v_L + v_R) / 2.0)

        sd_L = fgs_parser.get_scale_data(ev_L)
        sd_R = fgs_parser.get_scale_data(ev_R)
        new_sd = {}
        for ch in ("sY", "sCb", "sCr"):
            x_L = sd_L.get(ch, {}).get("x", [])
            y_L = sd_L.get(ch, {}).get("y", [])
            x_R = sd_R.get(ch, {}).get("x", [])
            y_R = sd_R.get(ch, {}).get("y", [])
            ml = min(len(x_L), len(x_R))
            new_x = [int(round((a + b) / 2.0)) for a, b in zip(x_L[:ml], x_R[:ml])]
            new_y = [int(round((a + b) / 2.0)) for a, b in zip(y_L[:ml], y_R[:ml])]
            new_sd[ch] = {"x": new_x, "y": new_y}

        cy_L, cb_L, cr_L = fgs_parser.extract_ar_coeffs_from_raw_lines(
            ev_L.get("raw_lines", [])
        )
        cy_R, cb_R, cr_R = fgs_parser.extract_ar_coeffs_from_raw_lines(
            ev_R.get("raw_lines", [])
        )

        def avg_coeffs(c1, c2):
            ml = min(len(c1), len(c2))
            return [int(round((a + b) / 2.0)) for a, b in zip(c1[:ml], c2[:ml])]

        new_cy = avg_coeffs(cy_L, cy_R)
        new_cb = avg_coeffs(cb_L, cb_R)
        new_cr = avg_coeffs(cr_L, cr_R)

        lag = new_p.get("ar_coeff_lag", 3)
        new_lines = []
        new_lines.append(_build_p_line(new_p))
        for ch in ("sY", "sCb", "sCr"):
            new_lines.append(_build_scale_line(ch, new_sd[ch]))
        new_lines.append(fgs_parser.format_c_line("cY", new_cy, lag))
        new_lines.append(fgs_parser.format_c_line("cCb", new_cb, lag))
        new_lines.append(fgs_parser.format_c_line("cCr", new_cr, lag))

        ep = list(ev_L.get("extra_params") or ["1", "7391", "1"])
        if len(ep) < 3:
            defaults = ["1", "7391", "1"]
            ep.extend(defaults[len(ep) : 3])
        ep[0] = "1"
        ep[2] = "1"

        new_ev = {
            "start_time": target_start,
            "end_time": target_end,
            "extra_params": ep,
            "e_line": f"E {target_start} {target_end} {' '.join(ep)}\n",
            "raw_lines": new_lines,
            "scale_data": new_sd,
            "p_params": new_p,
        }

        self.events[idx] = new_ev
        self._ensure_valid_master_chain()
        self.build_timeline()
        self._update_ui_state()

    def _create_default_event(self, start_ticks: int, end_ticks: int, template_ev=None) -> dict:
        import os
        from fgseditor_qt.core.app_paths import get_base_dir
        from fgseditor_qt.core.fgs_parser import parse_fgs_events

        new_ev = None
        if template_ev and fgs_parser.get_apply_grain(template_ev) != 0:
            new_ev = copy.deepcopy(template_ev)
            if "raw_lines" in new_ev:
                new_ev["raw_lines"] = [
                    l
                    for l in new_ev["raw_lines"]
                    if not (l.strip().split() and l.strip().split()[0].upper() == "E")
                ]

        if not new_ev:
            default_path = os.path.join(
                get_base_dir(), "Templates", "system", "default.txt"
            )
            try:
                with open(default_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    _, def_events = parse_fgs_events(content)
                    if def_events:
                        new_ev = copy.deepcopy(def_events[0])
            except Exception:
                pass

        if not new_ev:
            new_ev = {
                "extra_params": ["1", "7391", "1"],
                "raw_lines": [],
                "scale_data": None,
                "p_params": None,
            }

        extra = list(new_ev.get("extra_params") or ["1", "7391", "1"])
        if len(extra) < 3:
            defaults = ["1", "7391", "1"]
            extra.extend(defaults[len(extra) : 3])
        extra[0] = "1"
        extra[2] = "1"
        new_ev["extra_params"] = extra
        new_ev["start_time"] = start_ticks
        new_ev["end_time"] = end_ticks
        params_str = " ".join(extra)
        new_ev["e_line"] = f"E {start_ticks} {end_ticks} {params_str}\n"
        return new_ev

    def _add_event_after_event(self, idx: int):
        if idx < 0 or idx >= len(self.events):
            return

        fps = self._current_fps()
        prev_ev = self.events[idx]
        prev_end_ticks = prev_ev["end_time"]
        prev_end_frame = ticks_to_frames(prev_end_ticks, fps)

        new_start_frame = prev_end_frame
        new_start_ticks = prev_end_ticks

        default_dur_frames = max(24, int(round(fps * 2)))
        has_next = (idx + 1) < len(self.events)

        if has_next:
            next_ev = self.events[idx + 1]
            next_start_ticks = next_ev["start_time"]
            next_start_frame = ticks_to_frames(next_start_ticks, fps)
            if next_start_ticks <= new_start_ticks or next_start_frame <= new_start_frame:
                QMessageBox.information(
                    self,
                    "No Space",
                    f"Cannot add event after Event {idx + 1}:\n"
                    f"Event {idx + 2} starts immediately at frame {next_start_frame} without a gap.",
                )
                return
            new_end_frame = min(new_start_frame + default_dur_frames, next_start_frame)
            if new_end_frame == next_start_frame:
                new_end_ticks = next_start_ticks
            else:
                new_end_ticks = min(frames_to_ticks(new_end_frame, fps), next_start_ticks)
        else:
            vid_info = getattr(self.main_ui, "_video_info", None)
            from fgseditor_qt.math.time_utils import video_info_to_ticks
            vid_ticks = video_info_to_ticks(vid_info, fps=fps) if vid_info else 0
            vid_frames = ticks_to_frames(vid_ticks, fps) if vid_ticks > 0 else 0
            if vid_frames > 0:
                if new_start_frame >= vid_frames or new_start_ticks >= vid_ticks:
                    QMessageBox.information(
                        self,
                        "Video Duration Reached",
                        f"Cannot add event after Event {idx + 1}:\n"
                        f"Event already reaches the end of the video duration ({vid_frames} frames).",
                    )
                    return
                new_end_frame = min(new_start_frame + default_dur_frames, vid_frames)
                if new_end_frame == vid_frames:
                    new_end_ticks = vid_ticks
                else:
                    new_end_ticks = min(frames_to_ticks(new_end_frame, fps), vid_ticks)
            else:
                new_end_frame = new_start_frame + default_dur_frames
                new_end_ticks = frames_to_ticks(new_end_frame, fps)

        if new_end_ticks <= new_start_ticks:
            return

        new_ev = self._create_default_event(new_start_ticks, new_end_ticks, template_ev=prev_ev)

        self._push_undo()
        self.events.insert(idx + 1, new_ev)
        self.build_timeline()
        self._update_ui_state()

    def _add_event_at_position(self, click_xdata: float):
        if click_xdata is None:
            return

        fps = self._current_fps()
        click_ticks = seconds_to_ticks(click_xdata)
        click_frame = ticks_to_frames(click_ticks, fps)

        prev_idx = None
        next_idx = None
        for i, ev in enumerate(self.events):
            if ev["end_time"] <= click_ticks:
                prev_idx = i
            if ev["start_time"] >= click_ticks and next_idx is None:
                next_idx = i

        default_dur_frames = max(24, int(round(fps * 2)))

        if prev_idx is not None:
            prev_end_ticks = self.events[prev_idx]["end_time"]
            prev_end_frame = ticks_to_frames(prev_end_ticks, fps)
            start_frame = max(prev_end_frame, click_frame)
            min_start_ticks = prev_end_ticks
        else:
            prev_end_ticks = 0
            prev_end_frame = 0
            start_frame = max(0, click_frame)
            min_start_ticks = 0

        vid_info = getattr(self.main_ui, "_video_info", None)
        from fgseditor_qt.math.time_utils import video_info_to_ticks
        vid_ticks = video_info_to_ticks(vid_info, fps=fps) if vid_info else 0
        vid_frames = ticks_to_frames(vid_ticks, fps) if vid_ticks > 0 else 0

        if next_idx is not None:
            next_start_ticks = self.events[next_idx]["start_time"]
            next_start_frame = ticks_to_frames(next_start_ticks, fps)
            if prev_idx is not None and next_start_frame > prev_end_frame and start_frame >= next_start_frame:
                start_frame = max(prev_end_frame, next_start_frame - 1)
            if start_frame >= next_start_frame or min_start_ticks >= next_start_ticks:
                QMessageBox.information(
                    self,
                    "No Gap",
                    f"Cannot add event: No space before Event {next_idx + 1} (starts at frame {next_start_frame}).",
                )
                return
            end_frame = min(start_frame + default_dur_frames, next_start_frame)
            max_end_ticks = next_start_ticks
        else:
            next_start_ticks = None
            next_start_frame = None
            if vid_frames > 0:
                if start_frame >= vid_frames or min_start_ticks >= vid_ticks:
                    QMessageBox.information(
                        self,
                        "Video Duration Reached",
                        f"Cannot add event at frame {start_frame}:\n"
                        f"Position is beyond the video duration ({vid_frames} frames).",
                    )
                    return
                end_frame = min(start_frame + default_dur_frames, vid_frames)
                max_end_ticks = vid_ticks
            else:
                end_frame = start_frame + default_dur_frames
                max_end_ticks = None

        if prev_idx is not None and start_frame == prev_end_frame:
            new_start_ticks = prev_end_ticks
        else:
            new_start_ticks = max(frames_to_ticks(start_frame, fps), min_start_ticks)

        if next_idx is not None and end_frame == next_start_frame:
            new_end_ticks = next_start_ticks
        else:
            new_end_ticks = frames_to_ticks(end_frame, fps)
            if max_end_ticks is not None:
                new_end_ticks = min(new_end_ticks, max_end_ticks)

        if new_end_ticks <= new_start_ticks:
            return

        tmpl = self.events[prev_idx] if prev_idx is not None else (self.events[0] if self.events else None)
        new_ev = self._create_default_event(new_start_ticks, new_end_ticks, template_ev=tmpl)

        self._push_undo()
        insert_at = (prev_idx + 1) if prev_idx is not None else 0
        self.events.insert(insert_at, new_ev)
        self.build_timeline()
        self._update_ui_state()

    def _add_event_from_context(self, idx, click_xdata):
        self._add_event_after_event(idx)

    def _ticks_to_str(self, ticks):
        fmt = self.time_format_combo.currentText()
        fps = self._current_fps()
        if fmt == "Frames":
            return str(ticks_to_frames(ticks, fps))
        elif fmt == "Seconds":
            return f"{ticks_to_seconds(ticks):.4f}"
        else:
            return ticks_to_timecode(ticks)

    def _str_to_ticks(self, text):
        fmt = self.time_format_combo.currentText()
        fps = self._current_fps()
        try:
            if fmt == "Frames":
                t = frames_to_ticks(int(text), fps)
            elif fmt == "Seconds":
                t = seconds_to_ticks(float(text))
            else:
                t = timecode_to_ticks(text)
            f = ticks_to_frames(t, fps)
            return frames_to_ticks(f, fps)
        except Exception:
            return None

    def _end_wheel_undo_gesture(self):
        self._wheel_gesture_active = False

    def _on_inline_editing_finished(self, is_start):
        self._end_wheel_undo_gesture()
        self._apply_inline_edit(is_start, push_undo=True)

    def _apply_inline_edit(self, is_start, push_undo=True):
        if not hasattr(self, "ax") or self.ax is None:
            return
        if self._editing_event_idx < 0 or self._editing_event_idx >= len(self.events):
            return

        idx = self._editing_event_idx
        ev = self.events[idx]

        old_start = ev["start_time"]
        old_end = ev["end_time"]

        if is_start:
            new_start = self._str_to_ticks(self.te_start_input.text())
            new_end = old_end
        else:
            new_start = old_start
            new_end = self._str_to_ticks(self.te_end_input.text())

        if new_start is None or new_end is None:
            self._update_inline_edit_bar_text()
            return

        if new_start == old_start and new_end == old_end:
            self._update_inline_edit_bar_text()
            return

        alter_neighbors = self.te_alter_neighbor.isChecked()
        fps = self._current_fps()
        vid_info = getattr(self.main_ui, "_video_info", None)
        from fgseditor_qt.math.time_utils import video_info_to_ticks
        vid_ticks = video_info_to_ticks(vid_info, fps=fps) if vid_info else 0

        if not alter_neighbors:
            if idx > 0:
                prev_end = self.events[idx - 1]["end_time"]
                if new_start < prev_end:
                    new_start = prev_end
            else:
                if new_start < 0:
                    new_start = 0

            if idx < len(self.events) - 1:
                next_start = self.events[idx + 1]["start_time"]
                if new_end > next_start:
                    new_end = next_start
            elif vid_ticks > 0:
                if new_end > vid_ticks:
                    new_end = vid_ticks

            if new_start >= new_end:
                self._update_inline_edit_bar_text()
                return

            if new_start == old_start and new_end == old_end:
                self._update_inline_edit_bar_text()
                return

            if push_undo:
                self._push_undo()

            ev["start_time"] = new_start
            ev["end_time"] = new_end
            self._sync_event_e_line(ev)
        else:
            if is_start:
                max_bound = min(
                    frames_to_ticks(max(0, ticks_to_frames(old_end, fps) - 1), fps),
                    old_end - 1,
                )
                if idx > 0:
                    prev_ev = self.events[idx - 1]
                    min_bound = max(
                        frames_to_ticks(ticks_to_frames(prev_ev["start_time"], fps) + 1, fps),
                        prev_ev["start_time"] + 1,
                    )
                    if min_bound > max_bound:
                        self._update_inline_edit_bar_text()
                        return
                    new_start = max(min_bound, min(max_bound, new_start))
                    if new_start == old_start and prev_ev["end_time"] == new_start:
                        self._update_inline_edit_bar_text()
                        return
                    if push_undo:
                        self._push_undo()
                    ev["start_time"] = new_start
                    prev_ev["end_time"] = new_start
                    self._sync_event_e_line(ev)
                    self._sync_event_e_line(prev_ev)
                else:
                    new_start = max(0, min(max_bound, new_start))
                    if new_start == old_start:
                        self._update_inline_edit_bar_text()
                        return
                    if push_undo:
                        self._push_undo()
                    ev["start_time"] = new_start
                    self._sync_event_e_line(ev)
            else:
                min_bound = max(
                    frames_to_ticks(ticks_to_frames(old_start, fps) + 1, fps),
                    old_start + 1,
                )
                if idx < len(self.events) - 1:
                    next_ev = self.events[idx + 1]
                    max_bound = min(
                        frames_to_ticks(max(0, ticks_to_frames(next_ev["end_time"], fps) - 1), fps),
                        next_ev["end_time"] - 1,
                    )
                    if min_bound > max_bound:
                        self._update_inline_edit_bar_text()
                        return
                    new_end = max(min_bound, min(max_bound, new_end))
                    if new_end == old_end and next_ev["start_time"] == new_end:
                        self._update_inline_edit_bar_text()
                        return
                    if push_undo:
                        self._push_undo()
                    ev["end_time"] = new_end
                    next_ev["start_time"] = new_end
                    self._sync_event_e_line(ev)
                    self._sync_event_e_line(next_ev)
                else:
                    new_end = max(min_bound, new_end)
                    if vid_ticks > 0:
                        new_end = min(vid_ticks, new_end)
                    if new_end <= old_start or new_end == old_end:
                        self._update_inline_edit_bar_text()
                        return
                    if push_undo:
                        self._push_undo()
                    ev["end_time"] = new_end
                    self._sync_event_e_line(ev)

        self.build_timeline()
        self._update_ui_state()
        self._update_inline_edit_bar_text()

    def _update_inline_edit_bar_text(self):
        if 0 <= self._editing_event_idx < len(self.events):
            ev = self.events[self._editing_event_idx]
            self.te_start_input.blockSignals(True)
            self.te_end_input.blockSignals(True)
            self.te_start_input.setText(self._ticks_to_str(ev["start_time"]))
            self.te_end_input.setText(self._ticks_to_str(ev["end_time"]))
            self.te_start_input.blockSignals(False)
            self.te_end_input.blockSignals(False)

    def _show_time_edit_bar(self, idx):
        self._editing_event_idx = idx
        self.te_label.setText(f"Ev {idx + 1}:")
        self.time_edit_bar.show()
        self._update_inline_edit_bar_text()

    def _hide_time_edit_bar(self):
        self.time_edit_bar.hide()
        self._editing_event_idx = -1

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent, Qt

        if (
            obj in (self.te_start_input, self.te_end_input)
            and event.type() == QEvent.Wheel
        ):
            delta = event.angleDelta().y()
            if delta != 0:
                is_start = obj == self.te_start_input
                modifier = event.modifiers()
                step = 10 if (modifier & Qt.ShiftModifier) else 1
                direction = 1 if delta > 0 else -1

                self._apply_wheel_step(is_start, direction * step)
                return True
        return super().eventFilter(obj, event)

    def _apply_wheel_step(self, is_start, frames_step):
        if self._editing_event_idx < 0 or self._editing_event_idx >= len(self.events):
            return

        obj = self.te_start_input if is_start else self.te_end_input
        current_ticks = self._str_to_ticks(obj.text())
        if current_ticks is None:
            return

        fps = self._current_fps()
        current_frames = ticks_to_frames(current_ticks, fps)
        new_frames = current_frames + frames_step

        new_ticks = frames_to_ticks(new_frames, fps)

        if not getattr(self, "_wheel_gesture_active", False):
            self._push_undo()
            self._wheel_gesture_active = True
        self._wheel_undo_timer.start(500)

        obj.setText(self._ticks_to_str(new_ticks))
        self._apply_inline_edit(is_start, push_undo=False)

    def _current_fps(self) -> float:
        return fps_from_label(self.fps_combo.currentText())

    def edit_time_bounds(self, idx):
        ev = self.events[idx]
        fps = self._current_fps()
        old_start_ticks = ev["start_time"]
        old_end_ticks = ev["end_time"]
        old_start_s = ticks_to_seconds(old_start_ticks)
        old_end_s = ticks_to_seconds(old_end_ticks)
        old_start_frames = ticks_to_frames(old_start_ticks, fps)
        old_end_frames = ticks_to_frames(old_end_ticks, fps)

        vid_info = getattr(self.main_ui, "_video_info", None)
        from fgseditor_qt.math.time_utils import video_info_to_ticks
        vid_ticks = video_info_to_ticks(vid_info, fps=fps) if vid_info else 0

        if idx > 0:
            min_start_ticks = self.events[idx - 1]["end_time"]
            min_start_s = ticks_to_seconds(min_start_ticks)
            min_start_frames = ticks_to_frames(min_start_ticks, fps)
        else:
            min_start_ticks = 0
            min_start_s = 0.0
            min_start_frames = 0

        if idx < len(self.events) - 1:
            max_end_ticks = self.events[idx + 1]["start_time"]
            max_end_s = ticks_to_seconds(max_end_ticks)
            max_end_frames = ticks_to_frames(max_end_ticks, fps)
        elif vid_ticks > 0:
            max_end_ticks = vid_ticks
            max_end_s = ticks_to_seconds(max_end_ticks)
            max_end_frames = ticks_to_frames(max_end_ticks, fps)
        else:
            max_end_ticks = None
            max_end_s = 99_999.0
            max_end_frames = 99_999_999

        from PySide6.QtWidgets import (
            QVBoxLayout,
            QHBoxLayout,
            QLabel,
            QSpinBox,
            QDoubleSpinBox,
            QPushButton,
            QRadioButton,
            QButtonGroup,
            QStackedWidget,
            QWidget,
        )

        dialog = QDialog(self)
        dialog.setWindowTitle(
            f"Edit Times for Event {idx + 1}  [{self.fps_combo.currentText()} fps]"
        )
        dialog.setMinimumWidth(400)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)

        toggle_layout = QHBoxLayout()
        toggle_layout.addWidget(QLabel("Input mode:"))
        rb_frames = QRadioButton("Frames")
        rb_seconds = QRadioButton("Seconds")
        rb_timecode = QRadioButton("Timecode")
        rb_frames.setChecked(True)
        grp = QButtonGroup(dialog)
        grp.addButton(rb_frames, 0)
        grp.addButton(rb_seconds, 1)
        grp.addButton(rb_timecode, 2)
        toggle_layout.addWidget(rb_frames)
        toggle_layout.addWidget(rb_seconds)
        toggle_layout.addWidget(rb_timecode)
        layout.addLayout(toggle_layout)

        stack = QStackedWidget()
        page_frames = QWidget()
        pf_layout = QVBoxLayout(page_frames)
        pf_layout.setContentsMargins(0, 0, 0, 0)
        start_spin_f = QSpinBox()
        start_spin_f.setMinimum(min_start_frames)
        start_spin_f.setMaximum(max(min_start_frames, max_end_frames - 1))
        start_spin_f.setValue(old_start_frames)
        pf_layout.addLayout(_row("Start frame:", start_spin_f))
        end_spin_f = QSpinBox()
        end_spin_f.setMinimum(max(min_start_frames + 1, old_start_frames + 1))
        end_spin_f.setMaximum(max(min_start_frames + 1, max_end_frames))
        end_spin_f.setValue(old_end_frames)
        pf_layout.addLayout(_row("End frame:  ", end_spin_f))
        start_spin_f.valueChanged.connect(
            lambda v: end_spin_f.setMinimum(min(end_spin_f.maximum(), v + 1))
        )
        end_spin_f.valueChanged.connect(
            lambda v: start_spin_f.setMaximum(max(start_spin_f.minimum(), v - 1))
        )
        stack.addWidget(page_frames)

        page_secs = QWidget()
        ps_layout = QVBoxLayout(page_secs)
        ps_layout.setContentsMargins(0, 0, 0, 0)
        start_spin_s = QDoubleSpinBox()
        start_spin_s.setDecimals(7)
        start_spin_s.setMinimum(min_start_s)
        start_spin_s.setMaximum(max(min_start_s, max_end_s - 1e-7))
        start_spin_s.setValue(old_start_s)
        ps_layout.addLayout(_row("Start (s):", start_spin_s))
        end_spin_s = QDoubleSpinBox()
        end_spin_s.setDecimals(7)
        end_spin_s.setMinimum(max(min_start_s + 1e-7, old_start_s + 1e-7))
        end_spin_s.setMaximum(max(min_start_s + 1e-7, max_end_s))
        end_spin_s.setValue(old_end_s)
        ps_layout.addLayout(_row("End (s):   ", end_spin_s))
        start_spin_s.valueChanged.connect(
            lambda v: end_spin_s.setMinimum(min(end_spin_s.maximum(), v + 1e-7))
        )
        end_spin_s.valueChanged.connect(
            lambda v: start_spin_s.setMaximum(max(start_spin_s.minimum(), v - 1e-7))
        )
        stack.addWidget(page_secs)

        page_tc = QWidget()
        ptc_layout = QVBoxLayout(page_tc)
        ptc_layout.setContentsMargins(0, 0, 0, 0)

        start_tc_input = QLineEdit()
        start_tc_input.setInputMask("99:99:99:999;_")
        start_tc_input.setText(ticks_to_timecode(old_start_ticks))
        ptc_layout.addLayout(_row("Start (TC):", start_tc_input))

        end_tc_input = QLineEdit()
        end_tc_input.setInputMask("99:99:99:999;_")
        end_tc_input.setText(ticks_to_timecode(old_end_ticks))
        ptc_layout.addLayout(_row("End (TC):  ", end_tc_input))

        stack.addWidget(page_tc)

        layout.addWidget(stack)

        chk_adjust_neighbors = QCheckBox("Adjust adjacent events (move shared boundaries)")
        if len(self.events) <= 1:
            chk_adjust_neighbors.setVisible(False)
        layout.addWidget(chk_adjust_neighbors)

        def _update_dialog_limits():
            adj = chk_adjust_neighbors.isChecked()
            if adj:
                if idx > 0:
                    prev_s_ticks = self.events[idx - 1]["start_time"]
                    eff_min_f = ticks_to_frames(prev_s_ticks, fps) + 1
                    eff_min_s = ticks_to_seconds(prev_s_ticks) + 1e-7
                else:
                    eff_min_f = 0
                    eff_min_s = 0.0
                if idx < len(self.events) - 1:
                    next_e_ticks = self.events[idx + 1]["end_time"]
                    eff_max_f = max(eff_min_f + 1, ticks_to_frames(next_e_ticks, fps) - 1)
                    eff_max_s = max(eff_min_s + 1e-7, ticks_to_seconds(next_e_ticks) - 1e-7)
                elif vid_ticks > 0:
                    eff_max_f = max(eff_min_f + 1, ticks_to_frames(vid_ticks, fps))
                    eff_max_s = max(eff_min_s + 1e-7, ticks_to_seconds(vid_ticks))
                else:
                    eff_max_f = 99_999_999
                    eff_max_s = 99_999.0
            else:
                eff_min_f = min_start_frames
                eff_min_s = min_start_s
                eff_max_f = max(eff_min_f + 1, max_end_frames)
                eff_max_s = max(eff_min_s + 1e-7, max_end_s)

            start_spin_f.setMinimum(eff_min_f)
            end_spin_f.setMaximum(eff_max_f)
            start_spin_f.setMaximum(max(eff_min_f, end_spin_f.value() - 1))
            end_spin_f.setMinimum(min(eff_max_f, start_spin_f.value() + 1))

            start_spin_s.setMinimum(eff_min_s)
            end_spin_s.setMaximum(eff_max_s)
            start_spin_s.setMaximum(max(eff_min_s, end_spin_s.value() - 1e-7))
            end_spin_s.setMinimum(min(eff_max_s, start_spin_s.value() + 1e-7))

        chk_adjust_neighbors.toggled.connect(lambda _: (_update_dialog_limits(), _update_hint()))

        hint = QLabel()
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)

        def _get_ticks():
            adj = chk_adjust_neighbors.isChecked()
            if rb_frames.isChecked():
                sf = start_spin_f.value()
                ef = end_spin_f.value()
                if not adj and idx > 0 and sf == min_start_frames:
                    s = min_start_ticks
                else:
                    s = frames_to_ticks(sf, fps)
                if not adj and max_end_ticks is not None and ef == max_end_frames:
                    e = max_end_ticks
                else:
                    e = frames_to_ticks(ef, fps)
            elif rb_seconds.isChecked():
                s = seconds_to_ticks(start_spin_s.value())
                e = seconds_to_ticks(end_spin_s.value())
            else:
                s = timecode_to_ticks(start_tc_input.text())
                e = timecode_to_ticks(end_tc_input.text())

            if not adj:
                s = max(min_start_ticks, s)
                if max_end_ticks is not None:
                    e = min(max_end_ticks, e)
                    s = min(s, max(min_start_ticks, e - 1))
                e = max(s + 1, e)
            else:
                lo = (
                    max(
                        frames_to_ticks(ticks_to_frames(self.events[idx - 1]["start_time"], fps) + 1, fps),
                        self.events[idx - 1]["start_time"] + 1,
                    )
                    if idx > 0
                    else 0
                )
                hi = (
                    min(
                        frames_to_ticks(max(0, ticks_to_frames(self.events[idx + 1]["end_time"], fps) - 1), fps),
                        self.events[idx + 1]["end_time"] - 1,
                    )
                    if idx < len(self.events) - 1
                    else (vid_ticks if vid_ticks > 0 else None)
                )
                s = max(lo, s)
                if hi is not None:
                    e = min(hi, e)
                    s = min(s, max(lo, e - 1))
                e = max(s + 1, e)
            return s, e

        def _update_hint():
            s, e = _get_ticks()
            hint.setText(
                f"→ {ticks_to_seconds(s):.4f}s … {ticks_to_seconds(e):.4f}s (duration: {ticks_to_seconds(e - s):.4f}s)"
            )

        for w in [start_spin_f, end_spin_f, start_spin_s, end_spin_s]:
            w.valueChanged.connect(_update_hint)
        for w in [start_tc_input, end_tc_input]:
            w.textChanged.connect(_update_hint)

        grp.idClicked.connect(stack.setCurrentIndex)
        _update_hint()

        btn_layout = QHBoxLayout()
        apply_btn = QPushButton("Apply")
        cancel_btn = QPushButton("Cancel")
        btn_layout.addWidget(apply_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        apply_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)

        if dialog.exec():
            new_s, new_e = _get_ticks()
            adj = chk_adjust_neighbors.isChecked()
            if new_s != old_start_ticks or new_e != old_end_ticks or adj:
                self._push_undo()
                ev["start_time"] = new_s
                ev["end_time"] = new_e
                self._sync_event_e_line(ev)
                if adj:
                    if idx > 0 and new_s != old_start_ticks:
                        self.events[idx - 1]["end_time"] = new_s
                        self._sync_event_e_line(self.events[idx - 1])
                    if idx < len(self.events) - 1 and new_e != old_end_ticks:
                        self.events[idx + 1]["start_time"] = new_e
                        self._sync_event_e_line(self.events[idx + 1])
                self.build_timeline()
                self._update_ui_state()

    def open_editor(self, idx):
        from fgseditor_qt.ui.dynamic.event_editor_window import EventEditorUI

        if getattr(self, "editor", None) is not None:
            if self.editor.event_data["event_idx"] == idx:
                self.editor.activateWindow()
                self.editor.raise_()
                return
            else:
                if not self.editor.close():
                    return

        event_dict = {"event": self.events[idx], "event_idx": idx}
        self.editor = EventEditorUI(self, event_dict)
        self.editor.show()

    def save_fgs(self):
        if getattr(self, "editor", None) is not None:
            try:
                if hasattr(self.editor, "editor") and self.editor.editor.has_open_ar_windows():
                    QMessageBox.warning(
                        self,
                        "AR Windows Open",
                        "Close all AR coefficient editor windows before saving.",
                        QMessageBox.Ok,
                    )
                    return False
                if hasattr(self.editor, "editor") and self.editor.editor.is_dirty():
                    reply = QMessageBox.question(
                        self,
                        "Unsaved Event Changes",
                        "The Event Editor has unsaved changes.\n\nDo you want to apply them before saving the FGS timeline?",
                        QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                        QMessageBox.Yes,
                    )
                    if reply == QMessageBox.Cancel:
                        return False
                    if reply == QMessageBox.Yes:
                        if not self.editor.save_event():
                            return False
            except Exception:
                pass


        errors = self._get_validation_errors()
        if errors and get_setting("show_unsafe_warnings", True):
            error_text = "\n".join(errors)
            reply = QMessageBox.warning(
                self,
                "Unsafe Settings",
                f"One or more events have stability or clipping issues:\n\n{error_text}\n\nSave anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return False

        from fgseditor_qt.core.fgs_save import save_dynamic_fgs

        default_name = "grain.tbl"
        if self.main_ui._video_path:
            video_base = os.path.splitext(os.path.basename(self.main_ui._video_path))[0]
            default_name = f"{video_base}.tbl"

        is_temp = getattr(self, "_is_temp", False) or not self.filepath or is_temp_filepath(self.filepath)
        force_path = None if is_temp else self.filepath

        if self.filepath and not is_temp:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Save Options")
            msg_box.setText(
                f"File already exists:\n{os.path.basename(self.filepath)}\n\nOverwrite or save as a new file?"
            )

            overwrite_btn = msg_box.addButton("Overwrite", QMessageBox.AcceptRole)
            save_as_btn = msg_box.addButton("Save As...", QMessageBox.ActionRole)
            cancel_btn = msg_box.addButton(QMessageBox.Cancel)

            msg_box.setDefaultButton(overwrite_btn)
            msg_box.exec()

            if msg_box.clickedButton() == cancel_btn:
                return False
            if msg_box.clickedButton() == save_as_btn:
                force_path = None

        self._clamp_last_event_to_video_duration()

        saved_path = save_dynamic_fgs(
            self,
            original_filepath=None if is_temp else self.filepath,
            header_lines=self.header_lines,
            events=self.events,
            default_name=default_name,
            force_path=force_path,
        )
        if saved_path:
            self.filepath = saved_path
            self._is_temp = False
            vname = os.path.basename(self.main_ui._video_path) if self.main_ui._video_path else ""
            if vname:
                self.file_label.setText(f"File: {self.filepath} | Video: {vname}")
            else:
                self.file_label.setText(f"File: {self.filepath}")
            self.original_events = _clone_events(self.events)
            self.original_fps_text = self.fps_combo.currentText()
            self._has_sanitization_changes = False
            self._update_ui_state()
            return True
        return False

    def save_binary(self):
        if self.main_ui._video_info:
            codec = self.main_ui._video_info.get("codec", "").lower()
            if codec and codec not in ("av1", "hevc"):
                reply = QMessageBox.warning(
                    self,
                    "Codec Warning",
                    f"Video codec '{codec.upper()}' may not support AFGS1 specification.\n\nContinue?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply == QMessageBox.No:
                    return

        is_dirty = (
            self.is_dirty()
            or not self.filepath
            or getattr(self, "_is_temp", False)
            or is_temp_filepath(self.filepath)
        )
        if is_dirty:
            reply = QMessageBox.question(
                self,
                "Save FGS Required",
                "The FGS table must be saved before exporting to binary AFGS1 payload.\n\nSave FGS table now?",
                QMessageBox.Save | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply != QMessageBox.Save:
                return
            if not self.save_fgs():
                return
            if self.is_dirty() or not self.filepath or is_temp_filepath(self.filepath):
                return

        fps = self._current_fps()
        if fps <= 0:
            fps = 24.0

        from fgseditor_qt.ui.dialogs.fgs_warning_dialog import ask_static_dynamic_mode

        static_mode = ask_static_dynamic_mode(self, title="Binary Export Mode")
        if static_mode is None:
            return

        default_out = os.path.splitext(self.filepath)[0] + ".bin"
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save AFGS1 Binary Payload",
            default_out,
            "Binary AFGS1 (*.bin)",
        )
        if not output_path:
            return

        from fgseditor_qt.core.binary_x265_FGS import parse_and_pack

        try:
            success = parse_and_pack(
                self.filepath,
                output_path,
                fps=fps,
                fallback_frames=150000,
                static_mode=static_mode,
            )
            if success:
                mode_label = "Static" if static_mode else "Dynamic"
                QMessageBox.information(
                    self,
                    "Success",
                    f"AFGS1 binary payload saved successfully ({mode_label} mode):\n{output_path}",
                )
            else:
                QMessageBox.critical(self, "Error", "Failed to parse FGS txt file.")
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"An error occurred while generating binary payload:\n{str(e)}",
            )

    def _get_file_label_text(self) -> str:
        fname = (
            "Unsaved FGS"
            if (
                getattr(self, "_is_temp", False)
                or not self.filepath
                or is_temp_filepath(self.filepath)
            )
            else self.filepath
        )
        vname = (
            os.path.basename(self.main_ui._video_path)
            if (
                hasattr(self, "main_ui")
                and self.main_ui
                and getattr(self.main_ui, "_video_path", None)
            )
            else ""
        )
        if vname:
            return f"File: {fname} | Video: {vname}"
        return f"File: {fname}"

    def _refresh_file_label(self):
        if hasattr(self, "file_label"):
            self.file_label.setText(self._get_file_label_text())

    def show_status_message(self, text: str, timeout_ms: int = 3000):
        if hasattr(self, "file_label"):
            orig = self._get_file_label_text()
            self.file_label.setText(f"{orig}  —  [{text}]")
            QTimer.singleShot(timeout_ms, self._refresh_file_label)
        if (
            hasattr(self, "main_ui")
            and hasattr(self.main_ui, "statusBar")
            and callable(self.main_ui.statusBar)
        ):
            sb = self.main_ui.statusBar()
            if sb:
                sb.showMessage(text, timeout_ms)

    def statusBar(self):
        if (
            hasattr(self, "main_ui")
            and hasattr(self.main_ui, "statusBar")
            and callable(self.main_ui.statusBar)
        ):
            return self.main_ui.statusBar()
        return None

    def set_file_label(self, text: str):
        self.file_label.setText(text)

    def set_save_apply_enabled(self, enabled: bool, tooltip: str = ""):
        self._save_apply_enabled_state = bool(enabled)
        self.save_apply_btn.setVisible(True)
        self.save_apply_btn.setEnabled(bool(enabled) and not self._is_clipping_busy())
        if tooltip:
            self.save_apply_btn.setToolTip(tooltip)

    def _update_save_apply_state(self):
        from fgseditor_qt.tools import fgs_tools

        video_path = getattr(self.main_ui, "_video_path", None)
        video_info = getattr(self.main_ui, "_video_info", None) or {}

        if not video_path:
            return

        codec = video_info.get("codec", "").lower()
        ext = os.path.splitext(video_path)[1].lower() if video_path else ""
        is_av1 = codec == "av1"
        is_supported_container = ext in (".mkv", ".ivf")
        preferred = fgs_tools.get_preferred_tool()

        enabled = False
        tooltip = ""
        if not is_av1:
            tooltip = f"Save & Apply is only available for AV1 videos (current: {codec.upper()})."
        elif not is_supported_container:
            tooltip = f"Save & Apply is only supported for .mkv and .ivf containers (current: {ext})."
        elif preferred is None:
            enabled = True
            tooltip = "No FGS tool found.\nPlease check Settings."
        else:
            enabled = True
            tooltip = f"Save FGS and apply grain to video ({preferred})."

        self.set_save_apply_enabled(enabled, tooltip)

    def save_and_apply(self):
        if getattr(self, "editor", None) is not None:
            try:
                if hasattr(self.editor, "editor") and self.editor.editor.has_open_ar_windows():
                    QMessageBox.warning(
                        self,
                        "AR Windows Open",
                        "Close all AR coefficient windows before applying.",
                        QMessageBox.Ok,
                    )
                    return
            except Exception:
                pass

        video_path = getattr(self.main_ui, "_video_path", None)
        if not video_path:
            video_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select Source AV1 Video (.mkv, .ivf)",
                get_dialog_dir("last_video_dir"),
                "AV1 Video (*.mkv *.ivf);;All Files (*)",
            )
            if not video_path:
                return
            update_dialog_dir("last_video_dir", video_path)
            self.main_ui._video_path = video_path
            from fgseditor_qt.tools.video_probe import probe_video
            try:
                self.main_ui._video_info = probe_video(video_path)
            except Exception:
                self.main_ui._video_info = {}
            self._update_save_apply_state()

        video_info = getattr(self.main_ui, "_video_info", None) or {}
        codec = video_info.get("codec", "").lower()
        ext = os.path.splitext(video_path)[1].lower() if video_path else ""
        if (codec and codec != "av1") or ext not in (".mkv", ".ivf"):
            QMessageBox.critical(
                self,
                "Unsupported Video Format",
                "Save & Apply requires an AV1 video (.mkv or .ivf).\n\n"
                f"Current format: {codec.upper() if codec else 'Unknown'} ({ext})",
            )
            return

        from fgseditor_qt.tools import fgs_tools

        tool_name, tool_path = fgs_tools.get_active_tool_path()
        if tool_path is None:
            QMessageBox.critical(
                self,
                "FGS Tool Not Found",
                "No FGS tool found.\n\nPlease check Settings.",
            )
            return

        self._clamp_last_event_to_video_duration()

        is_dirty = (
            self.is_dirty()
            or not self.filepath
            or getattr(self, "_is_temp", False)
            or is_temp_filepath(self.filepath)
        )
        if is_dirty:
            reply = QMessageBox.question(
                self,
                "Save FGS Required",
                "The FGS table must be saved before applying it to the video.\n\nSave FGS table now?",
                QMessageBox.Save | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply != QMessageBox.Save:
                return
            if not self.save_fgs():
                return
            if self.is_dirty() or not self.filepath or is_temp_filepath(self.filepath):
                return

        errors = self._get_validation_errors()
        if errors and get_setting("show_unsafe_warnings", True):
            error_text = "\n".join(errors)
            reply = QMessageBox.warning(
                self,
                "Unsafe Settings",
                f"One or more events have stability or clipping issues:\n\n{error_text}\n\nContinue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return

        from fgseditor_qt.ui.dialogs.fgs_warning_dialog import ask_static_dynamic_mode

        static_mode = ask_static_dynamic_mode(self, title="Apply FGS Mode")
        if static_mode is None:
            return

        src_base = os.path.splitext(os.path.basename(video_path))
        src_ext = src_base[1] if len(src_base) > 1 else ".mkv"
        video_dir = os.path.dirname(video_path)

        base_name_candidate = f"{src_base[0]}_fgs_applied"
        default_out = os.path.join(video_dir, f"{base_name_candidate}{src_ext}")
        idx = 0
        while os.path.exists(default_out) or os.path.exists(
            os.path.join(video_dir, f"{base_name_candidate}.txt")
        ):
            idx += 1
            base_name_candidate = f"{src_base[0]}_fgs_applied ({idx})"
            default_out = os.path.join(video_dir, f"{base_name_candidate}{src_ext}")

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Output Video",
            default_out,
            "MKV Video (*.mkv);;All Files (*)",
        )
        if not output_path:
            return

        if os.path.abspath(output_path) == os.path.abspath(video_path):
            QMessageBox.warning(
                self,
                "Invalid Output Video",
                "The output video path cannot be the same as the source video.",
            )
            return

        from PySide6.QtWidgets import QProgressDialog, QApplication

        progress = QProgressDialog(
            "Applying film grain to video...",
            "Cancel",
            0,
            100,
            self,
        )
        progress.setWindowTitle("Applying FGS")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()

        def on_progress(pct: float, msg: str):
            progress.setValue(int(pct))
            progress.setLabelText(msg)
            QApplication.processEvents()

        def check_cancelled() -> bool:
            QApplication.processEvents()
            return progress.wasCanceled()

        success, msg = fgs_tools.apply_fgs(
            video_path,
            self.filepath,
            output_path,
            is_static=static_mode,
            progress_callback=on_progress,
            cancel_check=check_cancelled,
        )
        progress.close()

        if not success and msg == "Operation cancelled by user.":
            return

        if success:
            QMessageBox.information(
                self,
                "Success",
                f"Film grain applied successfully!\n\nOutput: {output_path}\nFGS applied: {self.filepath}",
            )
        else:
            QMessageBox.critical(
                self,
                "Apply Failed",
                f"Failed to apply film grain:\n\n{msg}\n\nFGS used: {self.filepath}",
            )

    def _finish_clipping_progress_ui(self) -> bool:
        """Restore canvas view and toolbar state after FixClippingWorker ends."""
        worker = getattr(self, "_fix_clipping_worker", None)
        self._fix_clipping_worker = None
        if worker is not None:
            worker.wait(2000)
            worker.deleteLater()
        if self.canvas is None:
            return False
        self.progress_cancel_btn.hide()
        self.progress_cancel_btn.setEnabled(True)
        self.progress_label.setText("Calculating timeline data...")
        self.main_stack.setCurrentWidget(self.canvas)
        self._update_ui_state()
        return True

    def _cancel_fix_clipping(self) -> None:
        """Request cancellation of a running background clipping fix."""
        worker = getattr(self, "_fix_clipping_worker", None)
        if worker is not None and worker.isRunning():
            self.progress_cancel_btn.setEnabled(False)
            self.progress_label.setText("Cancelling clipping fix...")
            worker.cancel()

    def _on_fix_clipping_cancelled(self) -> None:
        self._finish_clipping_progress_ui()

    def _on_fix_clipping_error(self, err_msg: str) -> None:
        if not self._finish_clipping_progress_ui():
            return
        QMessageBox.critical(
            self,
            "Fix Clipping Error",
            f"Failed to fix clipping:\n{err_msg}",
        )

    def _on_fix_clipping_ready(self, result: tuple) -> None:
        if not self._finish_clipping_progress_ui():
            return
        cloned_events, modified_count, max_shift_overall = result

        if modified_count == 0:
            QMessageBox.information(
                self,
                "Fix Clipping",
                "No clipping detected across all events and channels.",
            )
            return

        if max_shift_overall > 4:
            reply = QMessageBox.warning(
                self,
                "Fix Clipping Warning",
                "One or more events require an automatic shift greater than 4 positions "
                f"(maximum calculated shift: {max_shift_overall} positions).\n\n"
                "This might significantly alter grain behavior. It is recommended to manually reduce point intensities.\n\n"
                "Do you want to proceed with the automatic shift for all events anyway?",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if reply != QMessageBox.Yes:
                return

        self._push_undo()
        self.events = cloned_events
        self._has_sanitization_changes = True
        self.build_timeline()
        self._update_ui_state()

        QMessageBox.information(
            self,
            "Fix Clipping",
            f"Clipping fixed across {modified_count} event(s) in all channels.",
        )

    def fix_clipping_all_events(self) -> None:
        """Apply clipping fix across all events and channels off the UI thread."""
        if not self.events or self._is_clipping_busy() or self._is_timeline_busy():
            return

        from fgseditor_qt.ui.panels.utils import ask_fix_clipping_options

        proceed, fix_endpoints = ask_fix_clipping_options(self, is_dynamic=True)
        if not proceed:
            return

        if getattr(self, "editor", None) is not None:
            if not self.editor.close():
                return

        v_info = getattr(self.main_ui, "_video_info", None) or {}
        bit_depth = v_info.get("bit_depth", 8)
        is_444 = bool(v_info.get("is_444", False))

        cloned_events = _clone_events(self.events)

        self.progress_label.setText("Fixing clipping across timeline...")
        self.progress_bar.setValue(0)
        self.progress_cancel_btn.setEnabled(True)
        self.progress_cancel_btn.show()
        self.main_stack.setCurrentWidget(self.progress_container)
        self._apply_toolbar_busy_state(fix_busy=True, timeline_busy=False)

        worker = FixClippingWorker(
            cloned_events,
            bit_depth,
            v_info,
            is_444,
            fix_endpoints=fix_endpoints,
        )
        self._fix_clipping_worker = worker
        worker.progress.connect(self.progress_bar.setValue)
        worker.finished_fix.connect(self._on_fix_clipping_ready)
        worker.cancelled.connect(self._on_fix_clipping_cancelled)
        worker.error_occurred.connect(self._on_fix_clipping_error)
        worker.start()

    def save_plot_as_png(self):
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Plot",
            os.path.join(get_user_data_dir(), "timeline.png"),
            "PNG (*.png)",
        )
        if save_path:
            self.figure.savefig(save_path, dpi=300, bbox_inches="tight")

    def _on_scroll(self, event):
        if event.inaxes != self.ax or self._xlim_full is None:
            return

        base_scale = 1.2
        scale_factor = 1 / base_scale if event.step > 0 else base_scale

        cur_xlim = self.ax.get_xlim()
        cur_range = cur_xlim[1] - cur_xlim[0]

        bbox = self.ax.get_window_extent()
        rel_x = (event.x - bbox.x0) / bbox.width
        xdata_now = cur_xlim[0] + rel_x * cur_range

        new_range = cur_range * scale_factor

        new_xmin = xdata_now - new_range * rel_x
        new_xmax = xdata_now + new_range * (1 - rel_x)

        full_xmin, full_xmax = self._xlim_full

        if new_xmin < full_xmin and new_xmax > full_xmax:
            self.reset_zoom()
            return

        min_left = -max(1e-4, new_range * 0.008) if full_xmin < 0 else full_xmin
        if new_xmin < min_left:
            new_xmin = min_left
            new_xmax = min(full_xmax, new_xmin + new_range)
        if new_xmax > full_xmax:
            new_xmax = full_xmax
            new_xmin = max(min_left, new_xmax - new_range)

        self._zoom_xlim = (new_xmin, new_xmax)
        self.ax.set_xlim(new_xmin, new_xmax)

        if self._pan_active:
            self._pan_start_x = event.x
            self._pan_xlim_start = (new_xmin, new_xmax)

        self._update_labels()
        self.canvas.draw_idle()

    def _on_mouse_press(self, event):
        if event.inaxes == self.ax:
            if event.dblclick:
                self._select_active = False
                if (
                    event.button == 1
                    and event.xdata is not None
                    and not self._is_clipping_busy()
                    and not self._is_timeline_busy()
                    and bool(getattr(self, "_label_artists", None))
                ):
                    idx = self._find_event_at_x(event.xdata)
                    if idx is not None and 0 <= idx < len(self.events):
                        self.open_editor(idx)
                return

            if event.button == 3:
                self._pan_active = True
                self._pan_start_x = event.x
                self._pan_xlim_start = self.ax.get_xlim()
                self._right_click_press_pos = (event.x, event.y)
                self._right_click_xdata = event.xdata
            elif event.button == 1:
                self._select_active = True
                self._select_start_x = event.xdata
                if self._select_overlay:
                    self._select_overlay.remove()
                    self._select_overlay = None
                self.canvas.draw_idle()

    def _on_mouse_move(self, event):
        if self._select_active and event.inaxes == self.ax and event.xdata is not None:
            if self._select_overlay:
                self._select_overlay.remove()
            self._select_overlay = self.ax.axvspan(
                self._select_start_x, event.xdata, color="#4da6ff", alpha=0.3, zorder=10
            )
            self.canvas.draw_idle()

        if self._pan_active and event.inaxes == self.ax and self._xlim_full is not None:
            if hasattr(self, "_right_click_press_pos") and self._right_click_press_pos is not None:
                press_x, press_y = self._right_click_press_pos
                if event.x is not None and event.y is not None:
                    dist = ((event.x - press_x) ** 2 + (event.y - press_y) ** 2) ** 0.5
                    if dist < 5:
                        return

            dx_pixels = event.x - self._pan_start_x
            cur_xmin, cur_xmax = self._pan_xlim_start

            bbox = self.ax.get_window_extent()
            dx_data = dx_pixels * ((cur_xmax - cur_xmin) / bbox.width)

            new_xmin = cur_xmin - dx_data
            new_xmax = cur_xmax - dx_data

            full_xmin, full_xmax = self._xlim_full
            cur_range = cur_xmax - cur_xmin
            min_left = -max(1e-4, cur_range * 0.008) if full_xmin < 0 else full_xmin

            if new_xmax > full_xmax:
                diff = new_xmax - full_xmax
                new_xmax -= diff
                new_xmin -= diff
            if new_xmin < min_left:
                diff = min_left - new_xmin
                new_xmin += diff
                new_xmax += diff
            new_xmin = max(min_left, new_xmin)
            new_xmax = min(full_xmax, new_xmax)

            self._zoom_xlim = (new_xmin, new_xmax)
            self.ax.set_xlim(new_xmin, new_xmax)
            self._update_labels()
            self.canvas.draw_idle()

        # Hover tooltips for timeline events
        if (
            event.inaxes == self.ax
            and event.xdata is not None
            and not self._pan_active
            and not self._select_active
        ):
            hovered_idx = self._find_event_at_x(event.xdata)

            if hovered_idx is not None and hovered_idx < len(self.events):
                ev = self.events[hovered_idx]
                extra = ev.get("extra_params") or ["1", "7391", "1"]
                try:
                    ag = int(extra[0]) if len(extra) > 0 else 1
                    up = int(extra[2]) if len(extra) > 2 else 1
                except (ValueError, TypeError):
                    ag, up = 1, 1

                tip_parts = [f"Event {hovered_idx + 1}"]
                if ag == 0:
                    tip_parts.append("⚠ Film grain is disabled for this event (apply_grain = 0)")
                elif up == 0:
                    m_idx = fgs_parser.find_master_event_idx(self.events, hovered_idx)
                    if m_idx is not None:
                        tip_parts.append(f"↳ Linked to Event E{m_idx + 1} (update_parameters = 0)")
                    else:
                        tip_parts.append("↳ update_parameters = 0 (Uninitialized master)")
                else:
                    seed_val = extra[1] if len(extra) > 1 else "7391"
                    tip_parts.append(f"Active film grain (Seed: {seed_val})")
                    linked = fgs_parser.find_linked_event_indices(self.events, hovered_idx)
                    if linked:
                        if len(linked) <= 8:
                            linked_str = ", ".join(f"E{idx + 1}" for idx in linked)
                        else:
                            head = ", ".join(f"E{idx + 1}" for idx in linked[:6])
                            linked_str = f"{head}, ..., E{linked[-1] + 1} (+{len(linked) - 7} more)"
                        tip_parts.append(f"Master for linked event(s): {linked_str} (update_parameters = 0)")

                self.canvas.setToolTip("\n".join(tip_parts))
            else:
                self.canvas.setToolTip("")

    def _on_mouse_release(self, event):
        if event.button == 3:
            self._pan_active = False
            if hasattr(self, "_right_click_press_pos") and self._right_click_press_pos is not None:
                press_x, press_y = self._right_click_press_pos
                if event.x is not None and event.y is not None:
                    dist = ((event.x - press_x) ** 2 + (event.y - press_y) ** 2) ** 0.5
                    if dist < 5:
                        self._handle_right_click_anywhere(self._right_click_xdata)
                self._right_click_press_pos = None
                self._right_click_xdata = None
        elif event.button == 1 and self._select_active:
            self._select_active = False
            if self._select_start_x is not None and event.xdata is not None:
                xmin = min(self._select_start_x, event.xdata)
                xmax = max(self._select_start_x, event.xdata)

                bbox = self.ax.get_window_extent()
                cur_range = self.ax.get_xlim()[1] - self.ax.get_xlim()[0]
                drag_px = (xmax - xmin) * (bbox.width / cur_range) if cur_range > 0 else 0

                if drag_px > 5:
                    selected = []
                    for i, (t_s, t_e) in enumerate(
                        zip(self._ev_t_start, self._ev_t_end)
                    ):
                        mid_t = (t_s + t_e) / 2
                        if xmin <= mid_t <= xmax:
                            selected.append(i)

                    if len(selected) > 1:
                        self._show_bulk_delete_menu(selected)
                    else:
                        if self._select_overlay:
                            self._select_overlay.remove()
                            self._select_overlay = None
                        self.canvas.draw_idle()
                else:
                    if self._select_overlay:
                        self._select_overlay.remove()
                        self._select_overlay = None
                    ev_idx = self._find_event_at_x(event.xdata)
                    if ev_idx is not None:
                        self._show_time_edit_bar(ev_idx)
                    self.canvas.draw_idle()

    def _handle_right_click_anywhere(self, xdata):
        if xdata is None:
            return
        found_idx = self._find_event_at_x(xdata)
        if found_idx is not None:
            self._show_event_context_menu(found_idx, xdata)
        else:
            self._show_empty_space_context_menu(xdata)

    def _on_mouse_leave(self, event):
        self._pan_active = False
        self._select_active = False
        self.canvas.setToolTip("")

    def reset_zoom(self):
        if self._xlim_full is not None:
            self._zoom_xlim = None
            self.ax.set_xlim(*self._xlim_full)
            self._update_labels()
            self.canvas.draw_idle()

    def _show_bulk_delete_menu(self, selected_indices):
        menu = QMenu(self)
        del_menu = menu.addMenu(f"Bulk Delete ({len(selected_indices)} events)")
        action_del_simple = del_menu.addAction("Delete")
        action_del_align = del_menu.addAction("Delete and Fill Gap")
        action_del_interp = del_menu.addAction("Delete and Interpolate")

        first_idx = min(selected_indices)
        last_idx = max(selected_indices)

        if first_idx == 0 or last_idx == len(self.events) - 1:
            action_del_interp.setEnabled(False)

        action = menu.exec(QCursor.pos())

        if self._select_overlay:
            self._select_overlay.remove()
            self._select_overlay = None
        self.canvas.draw_idle()

        if action is None:
            return

        reply = QMessageBox.question(
            self,
            "Bulk Delete",
            f"Are you sure you want to delete {len(selected_indices)} events?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        def trigger_action():
            if action == action_del_simple:
                self._bulk_delete_simple(selected_indices)
            elif action == action_del_align:
                self._bulk_delete_align(selected_indices)
            elif action == action_del_interp:
                self._bulk_delete_interpolate(selected_indices)

        QTimer.singleShot(50, trigger_action)

    def _bulk_delete_simple(self, indices):
        self._push_undo()
        for idx in sorted(indices, reverse=True):
            self.events.pop(idx)
        self._ensure_valid_master_chain()
        self.build_timeline()
        self._update_ui_state()

    def _bulk_delete_align(self, indices):
        self._push_undo()
        indices = sorted(indices)
        first_idx = indices[0]
        last_idx = indices[-1]

        t_start = self.events[first_idx]["start_time"]
        t_end = self.events[last_idx]["end_time"]

        has_prev = first_idx > 0
        has_next = last_idx < len(self.events) - 1

        for idx in reversed(indices):
            self.events.pop(idx)

        if has_prev and has_next:
            fps = self._current_fps()
            mid_raw = (t_start + t_end) // 2
            if fps > 0:
                mid_f = ticks_to_frames(mid_raw, fps)
                prev_start_f = ticks_to_frames(self.events[first_idx - 1]["start_time"], fps)
                next_end_f = ticks_to_frames(self.events[first_idx]["end_time"], fps)
                mid_f = max(prev_start_f + 1, min(max(prev_start_f + 1, next_end_f - 1), mid_f))
                mid_t = frames_to_ticks(mid_f, fps)
            else:
                mid_t = mid_raw
            mid_t = max(
                self.events[first_idx - 1]["start_time"] + 1,
                min(self.events[first_idx]["end_time"] - 1, mid_t),
            )
            self.events[first_idx - 1]["end_time"] = mid_t
            self.events[first_idx]["start_time"] = mid_t
            self._sync_event_e_line(self.events[first_idx - 1])
            self._sync_event_e_line(self.events[first_idx])
        elif has_prev:
            self.events[first_idx - 1]["end_time"] = t_end
            self._sync_event_e_line(self.events[first_idx - 1])
        elif has_next:
            self.events[first_idx]["start_time"] = t_start
            self._sync_event_e_line(self.events[first_idx])

        self._ensure_valid_master_chain()
        self.build_timeline()
        self._update_ui_state()

    def _bulk_delete_interpolate(self, indices):
        indices = sorted(indices)
        first_idx = indices[0]
        last_idx = indices[-1]

        has_prev = first_idx > 0
        has_next = last_idx < len(self.events) - 1
        if not (has_prev and has_next):
            return

        self._push_undo()
        ev_L = self.events[first_idx - 1]
        ev_R = self.events[last_idx + 1]
        target_start = self.events[first_idx]["start_time"]
        target_end = self.events[last_idx]["end_time"]

        import math
        from fgseditor_qt.core import fgs_parser
        from fgseditor_qt.core.fgs_save import _build_p_line, _build_scale_line

        p_L = fgs_parser.get_p_params(ev_L)
        p_R = fgs_parser.get_p_params(ev_R)
        new_p = {}
        for k in fgs_parser.P_DEFAULTS:
            v_L = p_L.get(k, fgs_parser.P_DEFAULTS[k])
            v_R = p_R.get(k, fgs_parser.P_DEFAULTS[k])
            new_p[k] = math.ceil((v_L + v_R) / 2.0)

        sd_L = fgs_parser.get_scale_data(ev_L)
        sd_R = fgs_parser.get_scale_data(ev_R)
        new_sd = {}
        for ch in ("sY", "sCb", "sCr"):
            x_L = sd_L.get(ch, {}).get("x", [])
            y_L = sd_L.get(ch, {}).get("y", [])
            x_R = sd_R.get(ch, {}).get("x", [])
            y_R = sd_R.get(ch, {}).get("y", [])
            ml = min(len(x_L), len(x_R))
            new_x = [int(round((a + b) / 2.0)) for a, b in zip(x_L[:ml], x_R[:ml])]
            new_y = [int(round((a + b) / 2.0)) for a, b in zip(y_L[:ml], y_R[:ml])]
            new_sd[ch] = {"x": new_x, "y": new_y}

        cy_L, cb_L, cr_L = fgs_parser.extract_ar_coeffs_from_raw_lines(
            ev_L.get("raw_lines", [])
        )
        cy_R, cb_R, cr_R = fgs_parser.extract_ar_coeffs_from_raw_lines(
            ev_R.get("raw_lines", [])
        )

        def avg_coeffs(c1, c2):
            ml = min(len(c1), len(c2))
            return [int(round((a + b) / 2.0)) for a, b in zip(c1[:ml], c2[:ml])]

        new_cy = avg_coeffs(cy_L, cy_R)
        new_cb = avg_coeffs(cb_L, cb_R)
        new_cr = avg_coeffs(cr_L, cr_R)

        lag = new_p.get("ar_coeff_lag", 3)
        new_lines = []
        new_lines.append(_build_p_line(new_p))
        for ch in ("sY", "sCb", "sCr"):
            new_lines.append(_build_scale_line(ch, new_sd[ch]))
        new_lines.append(fgs_parser.format_c_line("cY", new_cy, lag))
        new_lines.append(fgs_parser.format_c_line("cCb", new_cb, lag))
        new_lines.append(fgs_parser.format_c_line("cCr", new_cr, lag))

        ep = list(ev_L.get("extra_params") or ["1", "7391", "1"])
        if len(ep) < 3:
            defaults = ["1", "7391", "1"]
            ep.extend(defaults[len(ep) : 3])
        ep[0] = "1"
        ep[2] = "1"

        new_ev = {
            "start_time": target_start,
            "end_time": target_end,
            "extra_params": ep,
            "e_line": f"E {target_start} {target_end} {' '.join(ep)}\n",
            "raw_lines": new_lines,
            "scale_data": new_sd,
            "p_params": new_p,
        }

        for idx in reversed(indices):
            self.events.pop(idx)

        self.events.insert(first_idx, new_ev)

        self._ensure_valid_master_chain()
        self.build_timeline()
        self._update_ui_state()


def _row(label_text: str, widget: QWidget) -> QHBoxLayout:
    hb = QHBoxLayout()
    hb.addWidget(QLabel(label_text))
    hb.addWidget(widget)
    return hb
