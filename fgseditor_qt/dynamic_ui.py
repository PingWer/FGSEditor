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
)
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.collections import LineCollection
from matplotlib.ticker import FuncFormatter
from . import fgs_parser
from . import fgs_math
from .app_paths import get_base_dir
from .shortcuts import create_standard_menu
from .time_utils import (
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
from functools import lru_cache
import datetime
from .settings_manager import get_setting

# Maximum number of event labels rendered (to avoid clutter + slowness)
_MAX_LABELS = 50

_cache_size = get_setting("fgs_grain_cache_size", 128)


@lru_cache(maxsize=_cache_size)
def _cached_compute_grain_extremes(
    seed, ar_lag, ar_shift, grain_scale_shift, cy_coeffs_tuple
):
    from .fgs_grain_sim import compute_grain_extremes

    return compute_grain_extremes(
        seed=seed,
        cy_coeffs=list(cy_coeffs_tuple),
        cb_coeffs=[],
        cr_coeffs=[],
        ar_lag=ar_lag,
        ar_shift=ar_shift,
        grain_scale_shift=grain_scale_shift,
    )


def _get_event_hash(ev: dict) -> str:
    import json

    ev_copy = {k: v for k, v in ev.items() if k not in ("start_time", "end_time")}
    return json.dumps(ev_copy, sort_keys=True)


def _process_timeline_event(args):
    i, key, ev = args
    from . import fgs_parser
    from .fgs_grain_sim import compute_amplitude_at_point

    evt_ctx = {"p_params": ev.get("p_params", fgs_parser.P_DEFAULTS)}
    ar_shift = fgs_parser.get_ar_coeff_shift(evt_ctx)
    ar_lag = fgs_parser.get_ar_coeff_lag(evt_ctx)
    scaling_shift = fgs_parser.get_scaling_shift(evt_ctx)
    gs_shift = fgs_parser.get_grain_scale_shift(evt_ctx)
    seed = fgs_parser.get_grain_seed(ev)

    cy_coeffs, _, _ = fgs_parser.extract_ar_coeffs_from_raw_lines(
        ev.get("raw_lines", [])
    )

    try:
        extremes = _cached_compute_grain_extremes(
            seed, ar_lag, ar_shift, gs_shift, tuple(cy_coeffs)
        )
        lmax = extremes["luma_max"]
    except Exception:
        lmax = 0

    scale_data = fgs_parser.get_scale_data(ev)
    sy_data = scale_data.get("sY", {})
    if not sy_data or not sy_data.get("y"):
        strength = 0.0
    else:
        sY_avg = sum(sy_data["y"]) / len(sy_data["y"])
        strength = compute_amplitude_at_point(lmax, sY_avg, scaling_shift)

    return i, key, strength


class TimelineDataWorker(QThread):
    finished_data = Signal(object)
    progress = Signal(int)

    def __init__(self, missing_events):
        super().__init__()
        import copy

        self.missing_events = copy.deepcopy(missing_events)

    def run(self):
        import concurrent.futures
        import os

        if not self.missing_events:
            self.progress.emit(100)
            self.finished_data.emit([])
            return

        from .settings_manager import get_setting

        num_cores = os.cpu_count() or 1
        max_workers = get_setting("timeline_max_workers", num_cores)
        max_workers = max(1, min(max_workers, num_cores * 2))

        chunksize = max(1, len(self.missing_events) // (max_workers * 4))

        results = []
        total = len(self.missing_events)

        with concurrent.futures.ProcessPoolExecutor(
            max_workers=max_workers
        ) as executor:
            for i, result in enumerate(
                executor.map(
                    _process_timeline_event,
                    self.missing_events,
                    chunksize=chunksize,
                )
            ):
                results.append(result)
                if i % max(1, total // 100) == 0 or i == total - 1:
                    self.progress.emit(int((i + 1) / total * 100))

        self.finished_data.emit(results)


class DynamicTimelineUI(QWidget):
    def __init__(self, main_ui, file_data):
        super().__init__()
        self.main_ui = main_ui
        self.setWindowTitle("FGS Dynamic Timeline")
        self.setMinimumSize(900, 500)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.file_data = file_data
        self.events = file_data["events"]
        self.original_events = copy.deepcopy(self.events)
        self.filepath = file_data["filepath"]
        self.header_lines = file_data["header_lines"]

        self.original_fps_text = DEFAULT_FPS_LABEL

        from .settings_manager import get_setting

        undo_size = get_setting("undo_stack_size", 100)
        self._undo_stack = deque(maxlen=undo_size)
        self._redo_stack = deque(maxlen=undo_size)

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self._do_autosave)
        from .settings_manager import get_setting

        interval_min = get_setting("autosave_interval_minutes", 5)
        if interval_min > 0:
            self.autosave_timer.start(interval_min * 60000)

        # Zoom / pan state
        self._xlim_full: tuple[float, float] | None = None
        self._zoom_xlim: tuple[float, float] | None = None
        self._pan_active = False
        self._pan_start_x: float | None = None
        self._pan_xlim_start: tuple[float, float] | None = None

        self._select_active = False
        self._select_start_x: float | None = None
        self._select_overlay = None

        # Pre-computed per-event data (rebuilt in build_timeline)
        self._ev_t_start: list[float] = []
        self._ev_t_end: list[float] = []
        self._ev_strength: list[float] = []
        self._line_collection = None
        self._scatter_collection = None

        self.setWindowTitle(f"Dynamic FGS Timeline - {os.path.basename(self.filepath)}")
        self.setMinimumSize(500, 800)

        layout = QVBoxLayout(self)

        top_frame = QFrame()
        top_frame.setObjectName("toolbar")
        top_layout = QHBoxLayout(top_frame)

        self.close_btn = QPushButton("Close FGS")
        self.close_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.close_btn.clicked.connect(self.close)
        top_layout.addWidget(self.close_btn, stretch=0)

        self.file_label = QLabel(f"File: {self.filepath}")
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
        from .settings_manager import get_setting

        default_fps = get_setting("default_fps", "24")
        for lbl, _ in COMMON_FPS:
            self.fps_combo.addItem(lbl)
        self.fps_combo.setCurrentText(default_fps)
        self.fps_combo.setToolTip(
            "Frame rate used to display and input event timestamps as frame numbers"
        )
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
        self.time_format_combo.setToolTip(
            "Display timeline in seconds, frames (based on FPS), or HH:MM:SS:mmm format"
        )
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

        self.reset_zoom_btn = QPushButton("⟳ Reset Zoom")
        self.reset_zoom_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.reset_zoom_btn.setToolTip(
            "Reset X-axis zoom to fit all events  (double-click on plot)"
        )
        self.reset_zoom_btn.clicked.connect(self.reset_zoom)
        mid_layout.addWidget(self.reset_zoom_btn, stretch=0)

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
        self.te_start_input.setFixedWidth(100)
        self.te_start_input.setStyleSheet("color: white; background: #111;")
        te_layout.addWidget(self.te_start_input)

        l2 = QLabel("End:")
        l2.setStyleSheet("color: white; background: transparent; border: none;")
        te_layout.addWidget(l2)
        self.te_end_input = QLineEdit()
        self.te_end_input.setFixedWidth(100)
        self.te_end_input.setStyleSheet("color: white; background: #111;")
        te_layout.addWidget(self.te_end_input)

        self.te_alter_neighbor = QCheckBox("Alter neighbors")
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
        # Code removed from here as it was moved up

        self._editing_event_idx = -1
        self.te_start_input.editingFinished.connect(
            lambda: self._apply_inline_edit(True)
        )
        self.te_end_input.editingFinished.connect(
            lambda: self._apply_inline_edit(False)
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
        prog_layout.addWidget(self.progress_label)
        prog_layout.addWidget(self.progress_bar)
        self.main_stack.addWidget(self.progress_container)

        self.build_timeline()
        self.canvas.mpl_connect("pick_event", self.on_pick)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_mouse_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_mouse_move)
        self.canvas.mpl_connect("button_release_event", self._on_mouse_release)
        self.canvas.mpl_connect("axes_leave_event", self._on_mouse_leave)
        self._update_ui_state()

    def is_dirty(self) -> bool:
        """Full check: events and FPS text."""
        if self.events != self.original_events:
            return True
        if self.fps_combo.currentText() != self.original_fps_text:
            return True
        return False

    def _get_validation_errors(self) -> list[str]:
        all_errors = []

        for idx, ev in enumerate(self.events):
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

    def _update_ui_state(self):
        dirty = self.is_dirty()

        errors = self._get_validation_errors()
        if errors:
            self.validation_warning_label.setText("⚠ UNSAFE SETTINGS")
            self.validation_warning_label.setToolTip("\n\n".join(errors))
            self.validation_warning_label.show()
        else:
            self.validation_warning_label.hide()

        self.save_btn.setEnabled(dirty)

        title = f"Dynamic FGS Timeline - {os.path.basename(self.filepath)}"
        if dirty:
            title += " *"
        self.setWindowTitle(title)

    def _on_fps_changed(self, text: str):
        self._update_ui_state()
        if self.time_format_combo.currentText() == "Frames":
            self.build_timeline()
        self._update_inline_edit_bar_text()

    def _on_time_format_changed(self, text: str):
        self.build_timeline()
        self._update_inline_edit_bar_text()

    def closeEvent(self, event):
        if self.is_dirty():
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes in the timeline. Save them before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Save:
                self.save_fgs()
                event.accept()
            elif reply == QMessageBox.Discard:
                event.accept()
            else:
                event.ignore()
                return

        if self.figure:
            import matplotlib.pyplot as plt

            plt.close(self.figure)
        if self.canvas:
            self.canvas.deleteLater()

        self.figure = None
        self.canvas = None
        self.ax = None
        self.lines = []
        self._line_collection = None
        self._scatter_collection = None
        self._select_overlay = None
        self._undo_stack.clear()
        self._redo_stack.clear()

        # Clean up MainUI state
        self.main_ui.filepath = None
        self.main_ui._current_event = None
        self.main_ui._video_path = None
        self.main_ui._video_info = None
        self.main_ui.editor.close_plotters()
        self.main_ui.editor.load_event(None)
        self.main_ui.editor.set_video_info(None)
        self.main_ui.editor.set_save_apply_enabled(False)
        self.main_ui.stacked_widget.setCurrentIndex(0)
        self.main_ui.setWindowTitle("FGSEditor")

        if self.autosave_timer.isActive():
            self.autosave_timer.stop()

        self.main_ui.show()
        super().closeEvent(event)

    def _do_autosave(self):
        if not self.is_dirty() or not self.events:
            return

        backup_dir = os.path.join(get_base_dir(), "backup")
        os.makedirs(backup_dir, exist_ok=True)

        is_static = True
        for ev in self.events:
            flags = fgs_parser.get_p_params(ev)
            if flags.get("overlap_flag", 1) == 1:
                is_static = False
                break

        mode_str = "static" if is_static else "dynamic"
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")

        if self.filepath and os.path.basename(self.filepath) != "Untitled":
            base_name = os.path.splitext(os.path.basename(self.filepath))[0]
        else:
            base_name = "Untitled"

        backup_filename = f"{base_name}_{timestamp}_{mode_str}.txt"
        backup_path = os.path.join(backup_dir, backup_filename)

        from .fgs_save import save_dynamic_fgs, save_static_fgs

        try:
            if is_static:
                save_static_fgs(self.events, backup_path, self.header_lines)
            else:
                save_dynamic_fgs(self.events, backup_path, self.header_lines)
        except Exception:
            pass  # Silent fail for background autosave

    def _push_undo(self):
        self._undo_stack.append(copy.deepcopy(self.events))
        self._redo_stack.clear()
        self._update_ui_state()

    def undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(copy.deepcopy(self.events))
        self.events = self._undo_stack.pop()
        self.build_timeline()
        self._update_ui_state()

    def redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(copy.deepcopy(self.events))
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
        self.lines = []
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
            self.progress_bar.setValue(0)
            self.main_stack.setCurrentWidget(self.progress_container)
            from PySide6.QtWidgets import QApplication

            QApplication.processEvents()

            if hasattr(self, "_timeline_worker") and self._timeline_worker.isRunning():
                try:
                    self._timeline_worker.finished_data.disconnect()
                    self._timeline_worker.progress.disconnect()
                except Exception:
                    pass

            self._timeline_worker = TimelineDataWorker(missing_events)
            self._timeline_worker.progress.connect(self.progress_bar.setValue)
            self._timeline_worker.finished_data.connect(self._on_timeline_data_ready)
            self._timeline_worker.start()
        else:
            self._on_timeline_data_ready([])

    def _on_timeline_data_ready(self, new_results):
        self.main_stack.setCurrentWidget(self.canvas)
        if not hasattr(self, "_strength_cache"):
            self._strength_cache = {}

        for idx, key, strength in new_results:
            self._strength_cache[key] = strength

        n = len(self.events)
        import numpy as np

        t_starts = np.empty(n)
        t_ends = np.empty(n)
        strengths = np.empty(n)

        from .time_utils import ticks_to_seconds

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
        self._label_artists: list = []

        min_s = float(strengths.min()) if n > 0 else 0.0
        max_s = float(strengths.max()) if n > 0 else 0.0
        min_t = float(t_starts.min()) if n > 0 else 0.0
        max_t = float(t_ends.max()) if n > 0 else 0.0
        margin_y = max(5, (max_s - min_s) * 0.3)
        margin_x = max(1, (max_t - min_t) * 0.05)
        self._margin_y = margin_y

        segs = [
            [(t_starts[i], strengths[i]), (t_ends[i], strengths[i])] for i in range(n)
        ]
        seg_colors = [colors_cycle[i % len(colors_cycle)] for i in range(n)]
        self._ev_colors = seg_colors

        lc = LineCollection(
            segs,
            colors=seg_colors,
            linewidths=4,
            capstyle="round",
            picker=12,
            clip_on=True,
        )
        self.ax.add_collection(lc)
        self._line_collection = lc

        mid_x = np.array(self._ev_mid_x)
        sc = self.ax.scatter(
            mid_x,
            strengths,
            c=seg_colors,
            s=80,
            zorder=3,
            clip_on=True,
            picker=12,
            edgecolors="white",
            linewidths=1,
            alpha=0.9,
        )
        self._scatter_collection = sc

        self._label_artists = []

        self.ax.set_title("Timeline Overview (Click segment to edit)", color="white")

        time_format = self.time_format_combo.currentText()
        fps = fps_from_label(self.fps_combo.currentText())

        if time_format == "Frames":
            self.ax.set_xlabel("Time (frames)", color="#cccccc")

            def frame_formatter(x, pos):
                frames = int(round(x * fps))
                return str(frames)

            self.ax.xaxis.set_major_formatter(FuncFormatter(frame_formatter))
        elif time_format == "Timestamp":
            self.ax.set_xlabel("Time (HH:MM:SS:mmm)", color="#cccccc")

            def timecode_formatter(x, pos):
                ticks = seconds_to_ticks(x)
                return ticks_to_timecode(ticks)

            self.ax.xaxis.set_major_formatter(FuncFormatter(timecode_formatter))
        else:  # Seconds
            self.ax.set_xlabel("Time (seconds)", color="#cccccc")
            self.ax.xaxis.set_major_formatter(FuncFormatter(lambda x, pos: f"{x:.2f}"))

        self.ax.set_ylabel("Effective Amplitude (px \u00b1)", color="#cccccc")
        self.ax.tick_params(colors="white")

        self._xlim_full = (min_t - margin_x, max_t + margin_x)
        if self._zoom_xlim:
            self.ax.set_xlim(*self._zoom_xlim)
        else:
            self.ax.set_xlim(*self._xlim_full)

        self.ax.set_ylim(max(0, min_s - margin_y), max_s + margin_y * 1.5)
        self.ax.grid(True, linestyle="--", color="#444444", alpha=0.3)

        self.figure.tight_layout()
        self._update_labels()
        self.canvas.draw_idle()

    def _update_labels(self):
        for artist in self._label_artists:
            try:
                artist.remove()
            except Exception:
                pass
        self._label_artists = []

        if not self._ev_t_start:
            return

        xmin, xmax = self.ax.get_xlim()

        visible_indices = [
            i
            for i, (ts, te) in enumerate(zip(self._ev_t_start, self._ev_t_end))
            if te >= xmin and ts <= xmax
        ]

        if len(visible_indices) > _MAX_LABELS:
            return

        margin_y = getattr(self, "_margin_y", 5)
        font_size = max(6, min(10, 10 - len(visible_indices) // 50))
        colors_cycle = self._COLORS

        for i in visible_indices:
            color = (self._ev_colors or colors_cycle)[i % len(colors_cycle)]
            txt = self.ax.text(
                self._ev_mid_x[i],
                self._ev_strength[i] + margin_y * 0.2,
                f"E{i + 1}",
                color=color,
                ha="center",
                va="bottom",
                fontsize=font_size,
                fontweight="bold",
                bbox=dict(boxstyle="round", fc="#222222", ec=color, alpha=0.9),
                clip_on=True,
            )
            self._label_artists.append(txt)

    def on_pick(self, event):
        if event.mouseevent is None or self._pan_active:
            return
        if event.artist not in (self._line_collection, self._scatter_collection):
            return

        indices = event.ind
        if len(indices) == 0:
            return
        idx = int(indices[0])

        if event.mouseevent.button == 1:
            self._show_time_edit_bar(idx)
        elif event.mouseevent.button == 3:
            self._show_context_menu(idx, event.mouseevent.xdata)

    def _show_context_menu(self, idx, xdata):
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        action_edit = menu.addAction("Modify Event")
        action_dur = menu.addAction("Change time bounds")
        menu.addSeparator()

        action_add = menu.addAction("Add Event Here")

        menu.addSeparator()
        del_menu = menu.addMenu("Delete")
        action_del_simple = del_menu.addAction("Delete only")
        action_del_align = del_menu.addAction("Delete and align with neighbours")
        action_del_interp = del_menu.addAction("Delete and interpolate with neighbours")

        if idx == 0 or idx == len(self.events) - 1:
            action_del_interp.setEnabled(False)

        action = menu.exec(QCursor.pos())
        if action == action_edit:
            self.open_editor(idx)
        elif action == action_dur:
            self.edit_time_bounds(idx)
        elif action == action_add:
            self._add_event_from_context(idx, xdata)
        elif action == action_del_simple:
            self._delete_event_simple(idx)
        elif action == action_del_align:
            self._delete_event_align(idx)
        elif action == action_del_interp:
            self._delete_event_interpolate(idx)

    def _delete_event_simple(self, idx):
        self._push_undo()
        self.events.pop(idx)
        self.build_timeline()
        self._update_ui_state()

    def _delete_event_align(self, idx):
        self._push_undo()
        ev = self.events[idx]
        t_start = ev["start_time"]
        t_end = ev["end_time"]

        has_prev = idx > 0
        has_next = idx < len(self.events) - 1

        self.events.pop(idx)

        if has_prev and has_next:
            mid_t = (t_start + t_end) // 2
            self.events[idx - 1]["end_time"] = mid_t
            self.events[idx]["start_time"] = mid_t
        elif has_prev:
            self.events[idx - 1]["end_time"] = t_end
        elif has_next:
            self.events[idx]["start_time"] = t_start

        self.build_timeline()
        self._update_ui_state()

    def _delete_event_interpolate(self, idx):
        has_prev = idx > 0
        has_next = idx < len(self.events) - 1
        if not (has_prev and has_next):
            return

        self._push_undo()
        ev_L = self.events[idx - 1]
        ev_R = self.events[idx + 1]
        target_start = self.events[idx]["start_time"]
        target_end = self.events[idx]["end_time"]

        import math
        from . import fgs_parser
        from .fgs_save import _build_p_line, _build_scale_line, _build_c_line

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
        new_lines.append(_build_c_line("cY", new_cy, lag))
        new_lines.append(_build_c_line("cCb", new_cb, lag))
        new_lines.append(_build_c_line("cCr", new_cr, lag))

        ep = list(ev_L.get("extra_params", ["1", "7391", "1"]))

        new_ev = {
            "start_time": target_start,
            "end_time": target_end,
            "extra_params": ep,
            "raw_lines": new_lines,
            "scale_data": new_sd,
            "p_params": new_p,
        }

        self.events[idx] = new_ev
        self.build_timeline()
        self._update_ui_state()

    def _add_event_from_context(self, idx, click_xdata):
        fps = self._current_fps()
        click_ticks = seconds_to_ticks(click_xdata)
        click_frame = ticks_to_frames(click_ticks, fps)

        new_ev_start = frames_to_ticks(click_frame, fps)
        new_ev_end = frames_to_ticks(click_frame + 1, fps)

        ev = self.events[idx]
        if new_ev_start <= ev["start_time"]:
            new_ev_start = ev["start_time"]
            new_ev_end = frames_to_ticks(ticks_to_frames(new_ev_start, fps) + 1, fps)
        if new_ev_end >= ev["end_time"]:
            new_ev_end = ev["end_time"]
            new_ev_start = frames_to_ticks(ticks_to_frames(new_ev_end, fps) - 1, fps)

        if new_ev_start >= new_ev_end:
            return

        import os
        from .app_paths import get_base_dir
        from .fgs_parser import parse_fgs_events

        default_path = os.path.join(
            get_base_dir(), "Templates", "system", "default.txt"
        )
        new_ev = copy.deepcopy(ev)
        try:
            with open(default_path, "r", encoding="utf-8") as f:
                content = f.read()
                _, def_events = parse_fgs_events(content)
                if def_events:
                    new_ev = def_events[0]
        except Exception:
            pass

        new_ev["start_time"] = new_ev_start
        new_ev["end_time"] = new_ev_end

        self._push_undo()

        right_ev = copy.deepcopy(ev)
        right_ev["start_time"] = new_ev_end

        ev["end_time"] = new_ev_start

        self.events.insert(idx + 1, new_ev)
        self.events.insert(idx + 2, right_ev)

        new_events = []
        for e in self.events:
            if e["start_time"] < e["end_time"]:
                new_events.append(e)
        self.events = new_events

        self.build_timeline()
        self._update_ui_state()

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

    def _apply_inline_edit(self, is_start):
        if not hasattr(self, "ax") or self.ax is None:
            return
        if self._editing_event_idx < 0 or self._editing_event_idx >= len(self.events):
            return

        idx = self._editing_event_idx
        ev = self.events[idx]

        new_start = self._str_to_ticks(self.te_start_input.text())
        new_end = self._str_to_ticks(self.te_end_input.text())

        if new_start is None or new_end is None:
            self._update_inline_edit_bar_text()
            return

        old_start = ev["start_time"]
        old_end = ev["end_time"]

        if new_start == old_start and new_end == old_end:
            return

        if new_start >= new_end:
            self._update_inline_edit_bar_text()
            return

        alter_neighbors = self.te_alter_neighbor.isChecked()
        fps = self._current_fps()
        min_frame_ticks = frames_to_ticks(1, fps) - frames_to_ticks(0, fps)

        self._push_undo()

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

            if new_start >= new_end:
                self.undo()
                self._update_inline_edit_bar_text()
                return

            ev["start_time"] = new_start
            ev["end_time"] = new_end
        else:
            ev["start_time"] = new_start
            ev["end_time"] = new_end

            if idx > 0:
                prev_ev = self.events[idx - 1]
                if new_start < prev_ev["start_time"] + min_frame_ticks:
                    new_start = prev_ev["start_time"] + min_frame_ticks
                    ev["start_time"] = new_start
                prev_ev["end_time"] = new_start
            else:
                if new_start < 0:
                    ev["start_time"] = 0

            if idx < len(self.events) - 1:
                next_ev = self.events[idx + 1]
                if new_end > next_ev["end_time"] - min_frame_ticks:
                    new_end = next_ev["end_time"] - min_frame_ticks
                    ev["end_time"] = new_end
                next_ev["start_time"] = new_end

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

        obj.setText(self._ticks_to_str(new_ticks))
        self._apply_inline_edit(is_start)

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

        if idx > 0:
            min_start_s = ticks_to_seconds(self.events[idx - 1]["end_time"])
            min_start_frames = (
                ticks_to_frames(self.events[idx - 1]["end_time"], fps) + 1
            )
        else:
            min_start_s = 0.0
            min_start_frames = 0

        from PySide6.QtWidgets import (
            QDialog,
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
        dialog.setMinimumWidth(360)
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
        start_spin_f.setMaximum(99_999_999)
        start_spin_f.setValue(old_start_frames)
        pf_layout.addLayout(_row("Start frame:", start_spin_f))
        end_spin_f = QSpinBox()
        end_spin_f.setMinimum(old_start_frames + 1)
        end_spin_f.setMaximum(99_999_999)
        end_spin_f.setValue(old_end_frames)
        pf_layout.addLayout(_row("End frame:  ", end_spin_f))
        start_spin_f.valueChanged.connect(lambda v: end_spin_f.setMinimum(v + 1))
        stack.addWidget(page_frames)

        page_secs = QWidget()
        ps_layout = QVBoxLayout(page_secs)
        ps_layout.setContentsMargins(0, 0, 0, 0)
        start_spin_s = QDoubleSpinBox()
        start_spin_s.setDecimals(7)
        start_spin_s.setMinimum(min_start_s)
        start_spin_s.setValue(old_start_s)
        ps_layout.addLayout(_row("Start (s):", start_spin_s))
        end_spin_s = QDoubleSpinBox()
        end_spin_s.setDecimals(7)
        end_spin_s.setMinimum(old_start_s + 1e-7)
        end_spin_s.setValue(old_end_s)
        ps_layout.addLayout(_row("End (s):   ", end_spin_s))
        start_spin_s.valueChanged.connect(lambda v: end_spin_s.setMinimum(v + 1e-7))
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
        hint = QLabel()
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)

        def _get_ticks():
            if rb_frames.isChecked():
                return (
                    frames_to_ticks(start_spin_f.value(), fps),
                    frames_to_ticks(end_spin_f.value(), fps),
                )
            elif rb_seconds.isChecked():
                return (
                    seconds_to_ticks(start_spin_s.value()),
                    seconds_to_ticks(end_spin_s.value()),
                )
            else:
                return (
                    timecode_to_ticks(start_tc_input.text()),
                    timecode_to_ticks(end_tc_input.text()),
                )

        def _update_hint():
            s, e = _get_ticks()
            hint.setText(
                f"→ {ticks_to_seconds(s):.4f}s  …  {ticks_to_seconds(e):.4f}s   ({e - s:,} exact 10^-7 seconds)"
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
            if new_s != old_start_ticks or new_e != old_end_ticks:
                self._push_undo()
                ev["start_time"] = new_s
                ev["end_time"] = new_e
                self.build_timeline()
                self._update_ui_state()

    def open_editor(self, idx):
        from .event_editor_window import EventEditorUI

        event_dict = {"event": self.events[idx], "event_idx": idx}
        self.editor = EventEditorUI(self, event_dict)
        self.editor.show()

    def save_fgs(self):
        from .settings_manager import get_setting

        errors = self._get_validation_errors()
        if errors and get_setting("show_unsafe_warnings", True):
            error_text = "\n".join(errors)
            reply = QMessageBox.warning(
                self,
                "Unsafe Settings",
                f"One or more events have stability or clipping issues:\n\n{error_text}\n\nAre you sure you want to save anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return False

        from .fgs_save import save_dynamic_fgs

        default_name = "modified_fgs.txt"
        if self.main_ui._video_path:
            video_base = os.path.splitext(os.path.basename(self.main_ui._video_path))[0]
            default_name = f"{video_base}.txt"

        saved_path = save_dynamic_fgs(
            self,
            original_filepath=self.filepath,
            header_lines=self.header_lines,
            events=self.events,
            default_name=default_name,
            force_path=self.filepath,
        )
        if saved_path:
            self.filepath = saved_path
            self.file_label.setText(f"File: {self.filepath}")
            self.original_events = copy.deepcopy(self.events)
            self.original_fps_text = self.fps_combo.currentText()
            self._update_ui_state()
            return True
        return False

    def save_binary(self):
        if not self.save_fgs():
            return

        if self.is_dirty():
            return

        import os
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        fps = self._current_fps()
        if fps <= 0:
            fps = 24.0

        # --- Static / Dynamic choice ---
        from PySide6.QtWidgets import (
            QDialog,
            QVBoxLayout,
            QHBoxLayout,
            QLabel,
            QPushButton,
        )
        from PySide6.QtCore import Qt

        mode_dialog = QDialog(self)
        mode_dialog.setWindowTitle("Binary Export Mode")
        mode_dialog.setMinimumWidth(420)
        _md_layout = QVBoxLayout(mode_dialog)
        _md_layout.setSpacing(12)

        _md_title = QLabel("<b>Choose the binary export mode:</b>")
        _md_title.setTextFormat(Qt.RichText)
        _md_layout.addWidget(_md_title)

        _md_static_desc = QLabel(
            "<b>Static</b> — Every event uses its own constant seed.\n"
            "Grain pattern repeats identically on every frame within each event."
        )
        _md_static_desc.setWordWrap(True)
        _md_layout.addWidget(_md_static_desc)

        _md_dynamic_desc = QLabel(
            "<b>Dynamic</b> — A different seed is chosen for each frame\n"
            "from the curated seed list (current behaviour)."
        )
        _md_dynamic_desc.setWordWrap(True)
        _md_layout.addWidget(_md_dynamic_desc)

        _md_btn_layout = QHBoxLayout()
        _md_static_btn = QPushButton("Static")
        _md_dynamic_btn = QPushButton("Dynamic")
        _md_cancel_btn = QPushButton("Cancel")
        _md_btn_layout.addWidget(_md_static_btn)
        _md_btn_layout.addWidget(_md_dynamic_btn)
        _md_btn_layout.addWidget(_md_cancel_btn)
        _md_layout.addLayout(_md_btn_layout)

        _md_result = [None]

        def _pick_static():
            _md_result[0] = True
            mode_dialog.accept()

        def _pick_dynamic():
            _md_result[0] = False
            mode_dialog.accept()

        _md_static_btn.clicked.connect(_pick_static)
        _md_dynamic_btn.clicked.connect(_pick_dynamic)
        _md_cancel_btn.clicked.connect(mode_dialog.reject)

        if mode_dialog.exec() != QDialog.Accepted or _md_result[0] is None:
            return

        static_mode = _md_result[0]
        # --- end Static / Dynamic choice ---

        default_out = os.path.splitext(self.filepath)[0] + ".bin"
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save AFGS1 Binary Payload",
            default_out,
            "Binary AFGS1 (*.bin)",
        )
        if not output_path:
            return

        from .binary_x265_FGS import parse_and_pack

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

    def save_plot_as_png(self):
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Plot",
            os.path.join(get_base_dir(), "timeline.png"),
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

        # Use pixel-space to find relative position for stable zoom
        bbox = self.ax.get_window_extent()
        rel_x = (event.x - bbox.x0) / bbox.width
        xdata_now = cur_xlim[0] + rel_x * cur_range

        new_range = cur_range * scale_factor

        new_xmin = xdata_now - new_range * rel_x
        new_xmax = xdata_now + new_range * (1 - rel_x)

        full_xmin, full_xmax = self._xlim_full

        # Prevent zooming out beyond original view
        if new_xmin < full_xmin and new_xmax > full_xmax:
            self.reset_zoom()
            return

        new_xmin = max(full_xmin, new_xmin)
        new_xmax = min(full_xmax, new_xmax)

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
                self.reset_zoom()
                return

            if event.button == 3:  # Right click
                self._pan_active = True
                self._pan_start_x = event.x
                self._pan_xlim_start = self.ax.get_xlim()
            elif event.button == 1:  # Left click selection
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
            dx_pixels = event.x - self._pan_start_x
            cur_xmin, cur_xmax = self._pan_xlim_start

            bbox = self.ax.get_window_extent()
            dx_data = dx_pixels * ((cur_xmax - cur_xmin) / bbox.width)

            new_xmin = cur_xmin - dx_data
            new_xmax = cur_xmax - dx_data

            full_xmin, full_xmax = self._xlim_full

            if new_xmin < full_xmin:
                diff = full_xmin - new_xmin
                new_xmin += diff
                new_xmax += diff
            if new_xmax > full_xmax:
                diff = new_xmax - full_xmax
                new_xmin -= diff
                new_xmax -= diff

            self._zoom_xlim = (new_xmin, new_xmax)
            self.ax.set_xlim(new_xmin, new_xmax)
            self._update_labels()
            self.canvas.draw_idle()

    def _on_mouse_release(self, event):
        if event.button == 3:
            self._pan_active = False
        elif event.button == 1 and self._select_active:
            self._select_active = False
            if self._select_start_x is not None and event.xdata is not None:
                xmin = min(self._select_start_x, event.xdata)
                xmax = max(self._select_start_x, event.xdata)

                # Minimum drag distance to consider it a selection
                if xmax - xmin > 0.001:
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
                    self.canvas.draw_idle()

    def _on_mouse_leave(self, event):
        self._pan_active = False
        self._select_active = False

    def reset_zoom(self):
        if self._xlim_full is not None:
            self._zoom_xlim = None
            self.ax.set_xlim(*self._xlim_full)
            self._update_labels()
            self.canvas.draw_idle()

    def _show_bulk_delete_menu(self, selected_indices):
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        del_menu = menu.addMenu(f"Bulk Delete ({len(selected_indices)} events)")
        action_del_simple = del_menu.addAction("Delete only")
        action_del_align = del_menu.addAction("Delete and align with neighbours")
        action_del_interp = del_menu.addAction("Delete and interpolate with neighbours")

        first_idx = min(selected_indices)
        last_idx = max(selected_indices)

        if first_idx == 0 or last_idx == len(self.events) - 1:
            action_del_interp.setEnabled(False)

        action = menu.exec(QCursor.pos())

        if self._select_overlay:
            self._select_overlay.remove()
            self._select_overlay = None
        self.canvas.draw_idle()

        if action == action_del_simple:
            self._bulk_delete_simple(selected_indices)
        elif action == action_del_align:
            self._bulk_delete_align(selected_indices)
        elif action == action_del_interp:
            self._bulk_delete_interpolate(selected_indices)

    def _bulk_delete_simple(self, indices):
        self._push_undo()
        for idx in sorted(indices, reverse=True):
            self.events.pop(idx)
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
            mid_t = (t_start + t_end) // 2
            self.events[first_idx - 1]["end_time"] = mid_t
            self.events[first_idx]["start_time"] = mid_t
        elif has_prev:
            self.events[first_idx - 1]["end_time"] = t_end
        elif has_next:
            self.events[first_idx]["start_time"] = t_start

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
        from . import fgs_parser
        from .fgs_save import _build_p_line, _build_scale_line, _build_c_line

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
        new_lines.append(_build_c_line("cY", new_cy, lag))
        new_lines.append(_build_c_line("cCb", new_cb, lag))
        new_lines.append(_build_c_line("cCr", new_cr, lag))

        ep = list(ev_L.get("extra_params", ["1", "7391", "1"]))

        new_ev = {
            "start_time": target_start,
            "end_time": target_end,
            "extra_params": ep,
            "raw_lines": new_lines,
            "scale_data": new_sd,
            "p_params": new_p,
        }

        for idx in reversed(indices):
            self.events.pop(idx)

        self.events.insert(first_idx, new_ev)

        self.build_timeline()
        self._update_ui_state()


def _row(label_text: str, widget: QWidget) -> QHBoxLayout:
    hb = QHBoxLayout()
    hb.addWidget(QLabel(label_text))
    hb.addWidget(widget)
    return hb
