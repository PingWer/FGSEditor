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
    QMenu,
    QCheckBox,
    QComboBox,
    QLineEdit,
)
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.collections import LineCollection
import numpy as np
from . import fgs_parser
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
)
from PySide6.QtCore import Qt

# Maximum number of event labels rendered (to avoid clutter + slowness)
_MAX_LABELS = 50


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

        self.original_autobalance = False
        self.original_fps_text = DEFAULT_FPS_LABEL

        self._undo_stack = deque(maxlen=100)
        self._redo_stack = deque(maxlen=100)

        # Zoom / pan state
        self._xlim_full: tuple[float, float] | None = None
        self._zoom_xlim: tuple[float, float] | None = None
        self._pan_active = False
        self._pan_start_x: float | None = None
        self._pan_xlim_start: tuple[float, float] | None = None

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

        info_label = QLabel(
            f"{len(self.events)} event(s) detected | Click a segment to edit that event"
        )
        info_label.setStyleSheet("color: #4da6ff;")
        mid_layout.addWidget(info_label, stretch=1)

        fps_label = QLabel("FPS:")
        fps_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        mid_layout.addWidget(fps_label, stretch=0)

        self.fps_combo = QComboBox()
        self.fps_combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        for lbl, _ in COMMON_FPS:
            self.fps_combo.addItem(lbl)
        self.fps_combo.setCurrentText(DEFAULT_FPS_LABEL)
        self.fps_combo.setToolTip(
            "Frame rate used to display and input event timestamps as frame numbers"
        )
        self.fps_combo.currentTextChanged.connect(self._update_ui_state)
        mid_layout.addWidget(self.fps_combo, stretch=0)

        self.autobalance_chk = QCheckBox("Strength Autobalance")
        self.autobalance_chk.setChecked(False)
        self.autobalance_chk.setStyleSheet("color: #aaaaaa;")
        self.autobalance_chk.setToolTip(
            "When ON (default), all events are scaled during save to ensure\n"
            "consistent perceived grain strength across different grain sizes."
        )
        self.autobalance_chk.stateChanged.connect(self._update_ui_state)
        mid_layout.addWidget(self.autobalance_chk, stretch=0)

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

        self.figure = Figure(figsize=(10, 3), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.figure.patch.set_facecolor("#1e1e1e")
        self.ax.set_facecolor("#111111")
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setStyleSheet("background-color: #1e1e1e;")
        layout.addWidget(self.canvas, stretch=1)

        self.build_timeline()
        self.canvas.mpl_connect("pick_event", self.on_pick)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_mouse_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_mouse_move)
        self.canvas.mpl_connect("button_release_event", self._on_mouse_release)
        self.canvas.mpl_connect("axes_leave_event", self._on_mouse_leave)
        self._update_ui_state()

    def is_dirty(self) -> bool:
        """Full check: events, FPS, and Autobalance flag."""
        if self.events != self.original_events:
            return True
        if self.autobalance_chk.isChecked() != self.original_autobalance:
            return True
        if self.fps_combo.currentText() != self.original_fps_text:
            return True
        return False

    def _get_validation_errors(self) -> list[str]:
        from .fgs_math import (
            extract_ar_coeffs_from_raw_lines,
            compute_export_scale_factor,
            validate_fgs_pipeline,
        )

        all_errors = []
        autobalance = self.autobalance_chk.isChecked()

        for idx, ev in enumerate(self.events):
            p_params = ev.get("p_params", {})
            grain_size = ev.get("grain_size", p_params.get("grain_size", 1))
            ar_shift = p_params.get("ar_coeff_shift", 8)

            cy_coeffs, cb_coeffs, cr_coeffs = extract_ar_coeffs_from_raw_lines(
                ev.get("raw_lines", [])
            )

            ev_has_errors = False
            for ch, coeffs, ch_key in [
                ("Y", cy_coeffs, "sY"),
                ("Cb", cb_coeffs, "sCb"),
                ("Cr", cr_coeffs, "sCr"),
            ]:
                ys = ev.get("scale_data", {}).get(ch_key, {}).get("y", [])
                export_scale = (
                    compute_export_scale_factor(grain_size, coeffs, ar_shift)
                    if autobalance
                    else 1.0
                )

                errors = validate_fgs_pipeline(coeffs, ar_shift, ys, export_scale)
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
        self._undo_stack.clear()
        self._redo_stack.clear()

        # Clean up MainUI state
        self.main_ui.filepath = None
        self.main_ui._current_event = None
        self.main_ui.current_data = {}
        self.main_ui.original_data = {}
        self.main_ui.original_p_params = {}
        self.main_ui.original_grain_size = 0
        self.main_ui.plotter.set_data({})
        self.main_ui.grain_preview.update_preview({})
        self.main_ui.stacked_widget.setCurrentIndex(0)
        self.main_ui.setWindowTitle("FGSEditor")

        self.main_ui.show()
        super().closeEvent(event)

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

        n = len(self.events)
        colors_cycle = self._COLORS

        # Pre-compute per-event values using numpy for speed
        t_starts = np.empty(n)
        t_ends = np.empty(n)
        strengths = np.empty(n)
        for i, ev in enumerate(self.events):
            t_starts[i] = ev["start_time"] * 1e-7
            t_ends[i] = ev["end_time"] * 1e-7
            strengths[i] = fgs_parser.avg_sy_strength(ev)

        self._ev_t_start = t_starts.tolist()
        self._ev_t_end = t_ends.tolist()
        self._ev_strength = strengths.tolist()
        self._ev_mid_x = ((t_starts + t_ends) / 2.0).tolist()
        self._label_artists: list = []

        min_s = float(strengths.min())
        max_s = float(strengths.max())
        min_t = float(t_starts.min())
        max_t = float(t_ends.max())
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
        self.ax.set_xlabel("Time (seconds)", color="#cccccc")
        self.ax.set_ylabel("Avg sY Strength", color="#cccccc")
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
        """Handle pick events on the LineCollection or Scatter dots."""
        # Only open menu on Left Click AND when not currently panning
        if event.mouseevent is None or event.mouseevent.button != 1 or self._pan_active:
            return
        if event.artist not in (self._line_collection, self._scatter_collection):
            return

        indices = event.ind
        if len(indices) == 0:
            return
        idx = int(indices[0])

        from PySide6.QtGui import QCursor

        menu = QMenu(self)
        action_edit = menu.addAction("Modify Event")
        action_dur = menu.addAction("Change time bounds")

        action = menu.exec(QCursor.pos())
        if action == action_edit:
            self.open_editor(idx)
        elif action == action_dur:
            self.edit_time_bounds(idx)

    def _current_fps(self) -> float:
        return fps_from_label(self.fps_combo.currentText())

    def edit_time_bounds(self, idx):
        ev = self.events[idx]
        fps = self._current_fps()
        old_start_ticks = ev["start_time"]
        old_end_ticks = ev["end_time"]
        old_start_s = old_start_ticks / 10_000_000
        old_end_s = old_end_ticks / 10_000_000
        old_start_frames = ticks_to_frames(old_start_ticks, fps)
        old_end_frames = ticks_to_frames(old_end_ticks, fps)

        if idx > 0:
            min_start_s = self.events[idx - 1]["end_time"] / 10_000_000
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

        from .time_utils import ticks_to_seconds, seconds_to_ticks

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
        errors = self._get_validation_errors()
        if errors:
            error_text = "\n".join(errors)
            reply = QMessageBox.warning(
                self,
                "Unsafe Settings",
                f"One or more events have stability or clipping issues:\n\n{error_text}\n\nAre you sure you want to save anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return

        from .fgs_save import save_dynamic_fgs

        saved = save_dynamic_fgs(
            self,
            original_filepath=self.filepath,
            header_lines=self.header_lines,
            events=self.events,
            autobalance=self.autobalance_chk.isChecked(),
        )
        if saved:
            self.original_events = copy.deepcopy(self.events)
            self.original_autobalance = self.autobalance_chk.isChecked()
            self.original_fps_text = self.fps_combo.currentText()
            self._update_ui_state()

    def save_plot_as_png(self):
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save Plot", os.path.join(get_base_dir(), "timeline.png"), "PNG (*.png)"
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

    def _on_mouse_move(self, event):
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

    def _on_mouse_leave(self, event):
        self._pan_active = False

    def reset_zoom(self):
        if self._xlim_full is not None:
            self._zoom_xlim = None
            self.ax.set_xlim(*self._xlim_full)
            self._update_labels()
            self.canvas.draw_idle()


def _row(label_text: str, widget: QWidget) -> QHBoxLayout:
    hb = QHBoxLayout()
    hb.addWidget(QLabel(label_text))
    hb.addWidget(widget)
    return hb
