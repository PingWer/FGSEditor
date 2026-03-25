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
)
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from . import fgs_parser
from .shortcuts import create_standard_menu
from .time_utils import (
    COMMON_FPS,
    DEFAULT_FPS_LABEL,
    fps_from_label,
    ticks_to_frames,
    frames_to_ticks,
)
from PySide6.QtCore import Qt


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

        self._undo_stack = deque(maxlen=100)
        self._redo_stack = deque(maxlen=100)

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

        from PySide6.QtWidgets import QComboBox

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
        mid_layout.addWidget(self.fps_combo, stretch=0)

        self.save_btn = QPushButton("Save FGS")
        self.save_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.save_btn.clicked.connect(self.save_file)
        mid_layout.addWidget(self.save_btn, stretch=0)

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

    def closeEvent(self, event):
        if self.events != self.original_events:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Do you want to save before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Save:
                self.save_file()
            elif reply == QMessageBox.Cancel:
                event.ignore()
                return

        if hasattr(self, "editor") and self.editor is not None:
            try:
                self.editor.close()
            except RuntimeError:
                pass

        self.figure.clear()
        self.canvas.deleteLater()
        self.figure = None
        self.canvas = None
        self.ax = None
        self.lines = []
        self._undo_stack.clear()
        self._redo_stack.clear()

        self.main_ui.close_fgs()
        self.main_ui.show()
        super().closeEvent(event)

    def _push_undo(self):
        self._undo_stack.append(copy.deepcopy(self.events))
        self._redo_stack.clear()

    def undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(copy.deepcopy(self.events))
        self.events = self._undo_stack.pop()
        self.build_timeline()

    def redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(copy.deepcopy(self.events))
        self.events = self._redo_stack.pop()
        self.build_timeline()

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.ControlModifier:
            if event.key() == Qt.Key_Z:
                self.undo()
                return
            if event.key() == Qt.Key_Y:
                self.redo()
                return
        super().keyPressEvent(event)

    def build_timeline(self):
        self.lines = []
        self.ax.clear()
        self.ax.set_facecolor("#111111")

        all_strengths = []
        max_t = 0
        min_t = float("inf")

        for ev in self.events:
            t_start = ev["start_time"] * 1e-7
            t_end = ev["end_time"] * 1e-7
            strength = fgs_parser.avg_sy_strength(ev)
            all_strengths.append(strength)
            max_t = max(max_t, t_end)
            min_t = min(min_t, t_start)

        if not all_strengths:
            self.canvas.draw()
            return

        colors = [
            "#4ade80",
            "#60a5fa",
            "#f87171",
            "#fbbf24",
            "#c084fc",
            "#f472b6",
            "#2dd4bf",
            "#a78bfa",
        ]

        min_s = min(all_strengths)
        max_s = max(all_strengths)
        margin_y = max(5, (max_s - min_s) * 0.3)
        margin_x = max(1, (max_t - min_t) * 0.05)

        self.lines = []
        for idx, ev in enumerate(self.events):
            t_start = ev["start_time"] * 1e-7
            t_end = ev["end_time"] * 1e-7
            strength = all_strengths[idx]
            color = colors[idx % len(colors)]

            (line,) = self.ax.plot(
                [t_start, t_end],
                [strength, strength],
                color=color,
                linewidth=4,
                solid_capstyle="round",
                picker=5,
            )
            line.event_idx = idx
            self.lines.append(line)

            self.ax.plot(
                (t_start + t_end) / 2, strength, marker="o", color=color, markersize=8
            )

            self.ax.text(
                (t_start + t_end) / 2,
                strength + margin_y * 0.2,
                f"E{idx + 1}",
                color=color,
                ha="center",
                va="bottom",
                fontsize=10,
                fontweight="bold",
                bbox=dict(boxstyle="round", fc="#222222", ec=color, alpha=0.9),
            )

        self.ax.set_title("Timeline Overview (Click segment to edit)", color="white")
        self.ax.set_xlabel("Time (seconds)", color="#cccccc")
        self.ax.set_ylabel("Avg sY Strength", color="#cccccc")
        self.ax.tick_params(colors="white")
        self.ax.set_xlim(min_t - margin_x, max_t + margin_x)
        self.ax.set_ylim(max(0, min_s - margin_y), max_s + margin_y * 1.5)
        self.ax.grid(True, linestyle="--", color="#444444", alpha=0.3)

        self.figure.tight_layout()
        self.canvas.draw()

    def on_pick(self, event):
        line = event.artist
        if hasattr(line, "event_idx"):
            idx = line.event_idx

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
        """Return the currently selected FPS value."""
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
            QMessageBox,
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
        _rb_style = (
            "QRadioButton { color: #dddddd; spacing: 6px; }"
            "QRadioButton::indicator { width: 14px; height: 14px; border-radius: 7px;"
            "  border: 2px solid #888888; background: #1e1e1e; }"
            "QRadioButton::indicator:checked { border: 2px solid #2a82da; background: #2a82da; }"
            "QRadioButton::indicator:hover { border-color: #4da6ff; }"
        )
        rb_frames = QRadioButton("Frames")
        rb_frames.setStyleSheet(_rb_style)
        rb_seconds = QRadioButton("Seconds")
        rb_seconds.setStyleSheet(_rb_style)
        rb_frames.setChecked(True)
        grp = QButtonGroup(dialog)
        grp.addButton(rb_frames, 0)
        grp.addButton(rb_seconds, 1)
        toggle_layout.addWidget(rb_frames)
        toggle_layout.addWidget(rb_seconds)
        toggle_layout.addStretch()
        layout.addLayout(toggle_layout)

        stack = QStackedWidget()

        # Frames
        page_frames = QWidget()
        pf_layout = QVBoxLayout(page_frames)
        pf_layout.setContentsMargins(0, 0, 0, 0)

        sf_row = QHBoxLayout()
        sf_row.addWidget(QLabel("Start frame:"))
        start_spin_f = QSpinBox()
        start_spin_f.setMinimum(min_start_frames)
        start_spin_f.setMaximum(99_999_999)
        start_spin_f.setValue(old_start_frames)
        sf_row.addWidget(start_spin_f)
        pf_layout.addLayout(sf_row)

        ef_row = QHBoxLayout()
        ef_row.addWidget(QLabel("End frame:  "))
        end_spin_f = QSpinBox()
        end_spin_f.setMinimum(old_start_frames + 1)
        end_spin_f.setMaximum(99_999_999)
        end_spin_f.setValue(old_end_frames)
        ef_row.addWidget(end_spin_f)
        pf_layout.addLayout(ef_row)

        start_spin_f.valueChanged.connect(lambda v: end_spin_f.setMinimum(v + 1))
        stack.addWidget(page_frames)

        # Seconds
        page_secs = QWidget()
        ps_layout = QVBoxLayout(page_secs)
        ps_layout.setContentsMargins(0, 0, 0, 0)

        ss_row = QHBoxLayout()
        ss_row.addWidget(QLabel("Start (s):"))
        start_spin_s = QDoubleSpinBox()
        start_spin_s.setDecimals(7)
        start_spin_s.setMinimum(min_start_s)
        start_spin_s.setMaximum(99_999.0)
        start_spin_s.setValue(old_start_s)
        ss_row.addWidget(start_spin_s)
        ps_layout.addLayout(ss_row)

        es_row = QHBoxLayout()
        es_row.addWidget(QLabel("End (s):   "))
        end_spin_s = QDoubleSpinBox()
        end_spin_s.setDecimals(7)
        end_spin_s.setMinimum(old_start_s + 1e-7)
        end_spin_s.setMaximum(99_999.0)
        end_spin_s.setValue(old_end_s)
        es_row.addWidget(end_spin_s)
        ps_layout.addLayout(es_row)

        start_spin_s.valueChanged.connect(lambda v: end_spin_s.setMinimum(v + 1e-7))
        stack.addWidget(page_secs)

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
            else:
                return (
                    seconds_to_ticks(start_spin_s.value()),
                    seconds_to_ticks(end_spin_s.value()),
                )

        def _update_hint():
            s, e = _get_ticks()
            hint.setText(
                f"→ {ticks_to_seconds(s):.4f}s  …  {ticks_to_seconds(e):.4f}s"
                f"   ({e - s:,} exact 10^-7 seconds)"
            )

        start_spin_f.valueChanged.connect(_update_hint)
        end_spin_f.valueChanged.connect(_update_hint)
        start_spin_s.valueChanged.connect(_update_hint)
        end_spin_s.valueChanged.connect(_update_hint)

        def _on_toggle(btn_id):
            stack.setCurrentIndex(btn_id)
            if btn_id == 0:
                start_spin_f.setValue(
                    ticks_to_frames(seconds_to_ticks(start_spin_s.value()), fps)
                )
                end_spin_f.setValue(
                    ticks_to_frames(seconds_to_ticks(end_spin_s.value()), fps)
                )
            else:
                start_spin_s.setValue(
                    ticks_to_seconds(frames_to_ticks(start_spin_f.value(), fps))
                )
                end_spin_s.setValue(
                    ticks_to_seconds(frames_to_ticks(end_spin_f.value(), fps))
                )
            _update_hint()

        grp.idClicked.connect(_on_toggle)
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
            new_start_ticks, new_end_ticks = _get_ticks()

            if new_start_ticks == old_start_ticks and new_end_ticks == old_end_ticks:
                return

            self._push_undo()
            ev["start_time"] = new_start_ticks
            ev["end_time"] = new_end_ticks

            shift_msg = ""
            if new_end_ticks > old_end_ticks and idx + 1 < len(self.events):
                next_start = self.events[idx + 1]["start_time"]
                overlap = new_end_ticks - next_start
                if overlap > 0:
                    for i in range(idx + 1, len(self.events)):
                        self.events[i]["start_time"] += overlap
                        self.events[i]["end_time"] += overlap
                    shift_frames = ticks_to_frames(overlap, fps)
                    shift_msg = (
                        f"\nSubsequent events shifted forward by "
                        f"{shift_frames} frames to prevent overlap."
                    )

            self.build_timeline()
            QMessageBox.information(
                self, "Times Updated", f"Event {idx + 1} times updated.{shift_msg}"
            )

    def open_editor(self, idx):
        from .event_editor_window import EventEditorUI

        event_dict = {"event": self.events[idx], "event_idx": idx}
        self.editor = EventEditorUI(self, event_dict)
        self.editor.show()

    def save_file(self):
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Modified Dynamic FGS",
            "modified_dynamic_fgs.txt",
            "Text Files (*.txt)",
        )
        if not save_path:
            return

        lines = list(self.header_lines)

        for ev in self.events:
            params = " ".join(ev["extra_params"])
            lines.append(f"E {ev['start_time']} {ev['end_time']} {params}\n")

            scale_data = ev["scale_data"]

            for raw_line in ev["raw_lines"]:
                tokens = raw_line.strip().split()
                if not tokens:
                    lines.append(raw_line)
                    continue

                prefix = tokens[0]
                if prefix in ("sY", "sCb", "sCr"):
                    data = scale_data[prefix]
                    pts = len(data["x"])
                    if pts == 0:
                        lines.append(f"{prefix} 0\n")
                    else:
                        pairs = []
                        for x, y in zip(data["x"], data["y"]):
                            pairs.extend([str(x), str(y)])
                        lines.append(f"{prefix} {pts} " + " ".join(pairs) + "\n")
                else:
                    lines.append(raw_line)

        with open(save_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        QMessageBox.information(self, "Success", "File saved successfully!")

    def save_plot_as_png(self):
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save Plot as PNG", "timeline.png", "PNG Images (*.png)"
        )
        if not save_path:
            return

        self.figure.savefig(save_path, dpi=300, bbox_inches="tight")
        QMessageBox.information(self, "Success", f"Plot saved to:\n{save_path}")
