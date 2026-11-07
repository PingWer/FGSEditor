from __future__ import annotations
import os

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QFileDialog,
    QProgressBar,
    QRadioButton,
    QButtonGroup,
    QCheckBox,
    QGroupBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QStackedWidget,
    QWidget,
    QMessageBox,
)

from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

from fgseditor_qt.core import fgs_parser
from fgseditor_qt.math import fgs_optimizer
from fgseditor_qt.math import time_utils
from fgseditor_qt.math import fgs_grain_sim


class OptimizerWorker(QThread):
    progress_updated = Signal(int, str)
    finished_data = Signal(bool, str, object)

    def __init__(
        self,
        fgs_path: str,
        video_path: str | None,
        scene_file: str | None,
        is_full_range: bool,
        ignore_chroma: bool,
        verify_ssim: bool = True,
        max_ssim_boundaries: int = 100,
        parent=None,
    ):
        super().__init__(parent)
        self.fgs_path = fgs_path
        self.video_path = video_path if video_path and os.path.isfile(video_path) else None
        self.scene_file = scene_file if scene_file and os.path.isfile(scene_file) else None
        self.is_full_range = is_full_range
        self.ignore_chroma = ignore_chroma
        self.verify_ssim = verify_ssim
        self.max_ssim_boundaries = max_ssim_boundaries
        self._is_cancelled = False


    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            self.progress_updated.emit(5, "Reading and sanitizing FGS file...")
            if not os.path.isfile(self.fgs_path):
                self.finished_data.emit(False, f"File not found: {self.fgs_path}", None)
                return

            with open(self.fgs_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            v_info = None
            if self.video_path and os.path.isfile(self.video_path):
                from fgseditor_qt.tools import video_probe
                try:
                    v_info = video_probe.probe_video(self.video_path)
                except Exception:
                    v_info = None

            headers, events, warnings = fgs_parser.parse_fgs_events(content, return_warnings=True, video_info=v_info)
            if not events:
                self.finished_data.emit(False, "No valid FGS events found in file.", None)
                return

            if len(events) == 1:
                self.progress_updated.emit(40, "Optimizing single event static FGS & calculating safe envelope...")
                orig_ev = events[0]
                opt_ev = fgs_optimizer.optimize_static_fgs(orig_ev, is_full_range=self.is_full_range)

                if v_info:
                    from fgseditor_qt.math import time_utils
                    try:
                        vid_ticks = time_utils.video_info_to_ticks(v_info)
                        if vid_ticks > 0 and opt_ev.get("end_time", 0) != vid_ticks:
                            opt_ev["end_time"] = vid_ticks
                            params_str = " ".join(opt_ev.get("extra_params", ["1", "7391", "1"]))
                            opt_ev["e_line"] = f"E {opt_ev['start_time']} {opt_ev['end_time']} {params_str}\n"
                    except Exception:
                        pass

                p = opt_ev.get("p_params") or fgs_parser.P_DEFAULTS
                cy, cb, cr = fgs_parser.extract_ar_coeffs_from_raw_lines(opt_ev.get("raw_lines", []))
                seed = fgs_parser.get_grain_seed(opt_ev)
                extremes = fgs_grain_sim.compute_grain_extremes(
                    seed=seed,
                    cy_coeffs=cy,
                    cb_coeffs=cb,
                    cr_coeffs=cr,
                    ar_lag=p.get("ar_coeff_lag", 3),
                    ar_shift=p.get("ar_coeff_shift", 6),
                    grain_scale_shift=0,
                )
                safe_env = fgs_optimizer.compute_safe_anti_clipping_envelope(
                    extremes["luma_min"], extremes["luma_max"], p.get("scaling_shift", 8), is_full_range=self.is_full_range
                )

                self.progress_updated.emit(100, "Static FGS optimization complete.")
                result_data = {
                    "is_dynamic": False,
                    "headers": headers,
                    "original_event": orig_ev,
                    "optimized_event": opt_ev,
                    "safe_envelope": safe_env,
                    "is_full_range": self.is_full_range,
                    "warnings": warnings,
                    "video_info": v_info,
                }
                self.finished_data.emit(True, "Static FGS optimized successfully.", result_data)

            else:
                def _prog_cb(pct: int, msg: str):
                    if not self._is_cancelled:
                        self.progress_updated.emit(pct, msg)

                optimized_events = fgs_optimizer.optimize_dynamic_fgs(
                    events,
                    is_full_range=self.is_full_range,
                    ignore_chroma=self.ignore_chroma,
                    progress_cb=_prog_cb,
                )

                if self._is_cancelled:
                    return

                v_path = self.video_path if self.verify_ssim else None
                optimized_events = fgs_optimizer.verify_scene_cuts(
                    optimized_events,
                    video_path=v_path,
                    scene_file=self.scene_file,
                    max_ssim_boundaries=self.max_ssim_boundaries,
                    progress_cb=_prog_cb,
                )

                if v_info and optimized_events:
                    from fgseditor_qt.math import time_utils
                    try:
                        vid_ticks = time_utils.video_info_to_ticks(v_info)
                        if vid_ticks > 0:
                            trimmed = [ev for ev in optimized_events if ev.get("start_time", 0) < vid_ticks]
                            if trimmed:
                                for ev in trimmed:
                                    if ev.get("end_time", 0) > vid_ticks:
                                        ev["end_time"] = vid_ticks
                                if trimmed[-1].get("end_time", 0) != vid_ticks:
                                    trimmed[-1]["end_time"] = vid_ticks
                                for ev in trimmed:
                                    params_str = " ".join(ev.get("extra_params", ["1", "7391", "1"]))
                                    ev["e_line"] = f"E {ev['start_time']} {ev['end_time']} {params_str}\n"
                                optimized_events = trimmed
                            elif optimized_events:
                                ev = optimized_events[0]
                                ev["start_time"] = 0
                                ev["end_time"] = vid_ticks
                                params_str = " ".join(ev.get("extra_params", ["1", "7391", "1"]))
                                ev["e_line"] = f"E {ev['start_time']} {ev['end_time']} {params_str}\n"
                                optimized_events = [ev]
                    except Exception:
                        pass

                result_data = {
                    "is_dynamic": True,
                    "headers": headers,
                    "raw_events": events,
                    "optimized_events": optimized_events,
                    "is_full_range": self.is_full_range,
                    "ignore_chroma": self.ignore_chroma,
                    "video_path": self.video_path,
                    "warnings": warnings,
                    "video_info": v_info,
                }

                self.finished_data.emit(True, "Dynamic FGS timeline optimized successfully.", result_data)

        except Exception as exc:
            self.finished_data.emit(False, f"Optimization failed: {exc}", None)


class FgsOptimizerDialog(QDialog):
    fgs_loaded = Signal(str)

    def __init__(self, parent=None, initial_fgs_path: str | None = None, initial_video_path: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("FGS Optimizer & Scene Analyzer")
        self.setMinimumSize(950, 700)
        self.resize(1050, 750)
        self.setAcceptDrops(True)

        self._worker: OptimizerWorker | None = None
        self._current_result: dict | None = None
        self._is_saved: bool = False

        self._setup_ui()

        if initial_fgs_path:
            self.fgs_edit.setText(initial_fgs_path)
        if initial_video_path:
            self.video_edit.setText(initial_video_path)
            self._on_video_path_changed(initial_video_path)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        input_group = QGroupBox("Inputs")
        input_layout = QVBoxLayout(input_group)
        input_layout.setSpacing(8)

        fgs_row = QHBoxLayout()
        fgs_label = QLabel("FGS File:*")
        fgs_label.setMinimumWidth(130)
        self.fgs_edit = QLineEdit()
        self.fgs_edit.setPlaceholderText("Select or drag & drop FGS file (.txt, .tbl)...")
        fgs_btn = QPushButton("Browse...")
        fgs_btn.setMinimumWidth(85)
        fgs_btn.clicked.connect(self._browse_fgs)
        fgs_row.addWidget(fgs_label)
        fgs_row.addWidget(self.fgs_edit)
        fgs_row.addWidget(fgs_btn)
        input_layout.addLayout(fgs_row)

        video_row = QHBoxLayout()
        video_label = QLabel("Video (Optional):")
        video_label.setMinimumWidth(130)
        self.video_edit = QLineEdit()
        self.video_edit.setPlaceholderText("Optional: Video file for scene cut verification...")
        self.video_edit.textChanged.connect(self._on_video_path_changed)
        video_btn = QPushButton("Browse...")
        video_btn.setMinimumWidth(85)
        video_btn.clicked.connect(self._browse_video)
        video_row.addWidget(video_label)
        video_row.addWidget(self.video_edit)
        video_row.addWidget(video_btn)
        input_layout.addLayout(video_row)

        scene_row = QHBoxLayout()
        scene_label = QLabel("Scene Cuts (Optional):")
        scene_label.setMinimumWidth(130)
        self.scene_edit = QLineEdit()
        self.scene_edit.setPlaceholderText("Optional: Scene cuts file (.txt, .json)...")
        scene_btn = QPushButton("Browse...")
        scene_btn.setMinimumWidth(85)
        scene_btn.clicked.connect(self._browse_scene)
        scene_row.addWidget(scene_label)
        scene_row.addWidget(self.scene_edit)
        scene_row.addWidget(scene_btn)
        input_layout.addLayout(scene_row)

        main_layout.addWidget(input_group)

        opts_group = QGroupBox("Optimizer Settings")
        opts_layout = QHBoxLayout(opts_group)
        opts_layout.setSpacing(20)

        range_box = QVBoxLayout()
        range_label = QLabel("<b>Color Range:</b>")
        self.radio_limited = QRadioButton("Limited Range (16–235)")
        self.radio_limited.setToolTip("Prevents noise clumping on near-black and near-white.")
        self.radio_limited.setChecked(True)
        self.radio_full = QRadioButton("Full Range (0–255)")
        self.radio_full.setToolTip("Applies grain across full 0–255 range.")
        range_bg = QButtonGroup(self)
        range_bg.addButton(self.radio_limited)
        range_bg.addButton(self.radio_full)
        range_box.addWidget(range_label)
        range_box.addWidget(self.radio_limited)
        range_box.addWidget(self.radio_full)
        opts_layout.addLayout(range_box)

        chroma_box = QVBoxLayout()
        chroma_label = QLabel("<b>Channels:</b>")
        self.chroma_check = QCheckBox("Ignore Chroma (Merge on Luma)")
        self.chroma_check.setToolTip("Merge scenes based on luma grain stability.")
        self.chroma_check.setChecked(True)
        chroma_box.addWidget(chroma_label)
        chroma_box.addWidget(self.chroma_check)
        chroma_box.addStretch()
        opts_layout.addLayout(chroma_box)

        verify_box = QVBoxLayout()
        verify_label = QLabel("<b>Verification:</b>")
        self.verify_ssim_check = QCheckBox("Verify Scene Cuts (SSIM)")
        self.verify_ssim_check.setToolTip("Verify scene cuts against source video using SSIM.")
        self.verify_ssim_check.setChecked(True)
        self.verify_ssim_check.setEnabled(False)
        verify_box.addWidget(verify_label)
        verify_box.addWidget(self.verify_ssim_check)
        verify_box.addStretch()
        opts_layout.addLayout(verify_box)

        main_layout.addWidget(opts_group)

        act_row = QHBoxLayout()
        self.start_btn = QPushButton("Start Optimization")
        self.start_btn.setMinimumHeight(38)
        self.start_btn.setStyleSheet("font-weight: bold; background-color: #2a82da; color: white; border-radius: 4px; padding: 6px 20px;")
        self.start_btn.clicked.connect(self._start_optimization)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setMinimumHeight(38)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_optimization)

        act_row.addWidget(self.start_btn)
        act_row.addWidget(self.cancel_btn)
        main_layout.addLayout(act_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(18)
        main_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready.")
        self.status_label.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        main_layout.addWidget(self.status_label)

        self.results_stack = QStackedWidget()

        self.placeholder_page = QWidget()
        pl_layout = QVBoxLayout(self.placeholder_page)
        pl_layout.setAlignment(Qt.AlignCenter)
        pl_msg = QLabel("No results yet.\nRun optimization to view scene metrics and plots.")
        pl_msg.setAlignment(Qt.AlignCenter)
        pl_msg.setStyleSheet("color: #666666; font-size: 14px;")
        pl_layout.addWidget(pl_msg)
        self.results_stack.addWidget(self.placeholder_page)

        self.dynamic_page = QWidget()
        dyn_layout = QVBoxLayout(self.dynamic_page)
        dyn_layout.setContentsMargins(0, 0, 0, 0)
        dyn_layout.setSpacing(8)

        self.dynamic_summary = QLabel()
        self.dynamic_summary.setStyleSheet("font-size: 13px; font-weight: bold; color: #4da6ff; padding: 4px;")
        dyn_layout.addWidget(self.dynamic_summary)

        self.scenes_table = QTableWidget()
        self.scenes_table.setColumnCount(7)
        self.scenes_table.setHorizontalHeaderLabels([
            "Scene", "Timecode", "Frames", "Merged", "Strength", "Cut Status", "Actions"
        ])
        self.scenes_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.scenes_table.horizontalHeader().setStretchLastSection(True)
        self.scenes_table.setAlternatingRowColors(True)
        self.scenes_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.scenes_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.scenes_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.scenes_table.setFocusPolicy(Qt.NoFocus)
        self.scenes_table.verticalHeader().setDefaultSectionSize(32)
        self.scenes_table.setStyleSheet(
            "QTableWidget { background-color: #1a1a1a; gridline-color: #333333; outline: none; } "
            "QTableWidget::item { outline: none; border: none; padding: 2px 4px; } "
            "QTableWidget::item:focus { outline: none; border: none; }"
        )
        dyn_layout.addWidget(self.scenes_table)
        self.results_stack.addWidget(self.dynamic_page)

        self.static_page = QWidget()
        stat_layout = QVBoxLayout(self.static_page)
        stat_layout.setContentsMargins(0, 0, 0, 0)
        stat_layout.setSpacing(8)

        self.static_summary = QLabel()
        self.static_summary.setStyleSheet("font-size: 13px; font-weight: bold; color: #4da6ff; padding: 4px;")
        stat_layout.addWidget(self.static_summary)

        self.static_figure = Figure(figsize=(7, 4), facecolor="#1e1e1e")
        self.static_canvas = FigureCanvas(self.static_figure)
        stat_layout.addWidget(self.static_canvas)
        self.results_stack.addWidget(self.static_page)

        main_layout.addWidget(self.results_stack, stretch=1)

        bottom_row = QHBoxLayout()
        self.save_btn = QPushButton("Save Optimized FGS...")
        self.save_btn.setMinimumWidth(160)
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save_optimized_fgs)

        self.open_editor_btn = QPushButton("Open in Editor")
        self.open_editor_btn.setMinimumWidth(120)
        self.open_editor_btn.setEnabled(False)
        self.open_editor_btn.clicked.connect(self._open_in_editor)

        self.close_btn = QPushButton("Close")
        self.close_btn.setMinimumWidth(80)
        self.close_btn.clicked.connect(self.close)

        bottom_row.addWidget(self.save_btn)
        bottom_row.addWidget(self.open_editor_btn)
        bottom_row.addStretch()
        bottom_row.addWidget(self.close_btn)
        main_layout.addLayout(bottom_row)

    def _on_video_path_changed(self, text: str):
        path = text.strip()
        has_video = bool(path and os.path.isfile(path))
        self.verify_ssim_check.setEnabled(has_video)

    def _browse_fgs(self):
        from fgseditor_qt.core.settings_manager import get_dialog_dir, update_dialog_dir

        fpath, _ = QFileDialog.getOpenFileName(
            self,
            "Select FGS Table File",
            get_dialog_dir("last_fgs_dir"),
            "FGS Files (*.txt *.tbl);;All Files (*)",
        )
        if fpath:
            update_dialog_dir("last_fgs_dir", fpath)
            self.fgs_edit.setText(fpath)

    def _browse_video(self):
        from fgseditor_qt.core.settings_manager import get_dialog_dir, update_dialog_dir

        fpath, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video File",
            get_dialog_dir("last_video_dir"),
            "Video Files (*.mkv *.mp4 *.ivf *.hevc *.webm *.avi);;All Files (*)",
        )
        if fpath:
            update_dialog_dir("last_video_dir", fpath)
            self.video_edit.setText(fpath)
            self._on_video_path_changed(fpath)

    def _browse_scene(self):
        fpath, _ = QFileDialog.getOpenFileName(
            self, "Select Scene Cut File", "", "Scene Cut Files (*.txt *.json);;All Files (*)"
        )
        if fpath:
            self.scene_edit.setText(fpath)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            path = urls[0].toLocalFile()
            event.acceptProposedAction()
            ext = os.path.splitext(path)[1].lower()
            if ext in (".txt", ".tbl"):
                QTimer.singleShot(0, lambda p=path: self.fgs_edit.setText(p))
            elif ext in (".mkv", ".mp4", ".ivf", ".hevc", ".webm", ".avi", ".mov", ".ts", ".flv"):
                def _handle_opt_video(p):
                    self.video_edit.setText(p)
                    self._on_video_path_changed(p)

                QTimer.singleShot(0, lambda: _handle_opt_video(path))
            elif ext in (".json",):
                QTimer.singleShot(0, lambda p=path: self.scene_edit.setText(p))

    def _start_optimization(self):
        fgs_path = self.fgs_edit.text().strip()
        if not fgs_path or not os.path.isfile(fgs_path):
            QMessageBox.warning(self, "Missing File", "Please select a valid FGS table file.")
            return

        video_path = self.video_edit.text().strip() or None
        scene_file = self.scene_edit.text().strip() or None
        is_full_range = self.radio_full.isChecked()
        ignore_chroma = self.chroma_check.isChecked()
        verify_ssim = self.verify_ssim_check.isChecked() and self.verify_ssim_check.isEnabled()

        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.save_btn.setEnabled(False)
        self.open_editor_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.status_label.setText("Starting optimizer worker...")

        self._worker = OptimizerWorker(
            fgs_path=fgs_path,
            video_path=video_path,
            scene_file=scene_file,
            is_full_range=is_full_range,
            ignore_chroma=ignore_chroma,
            verify_ssim=verify_ssim,
            parent=self,
        )

        self._worker.progress_updated.connect(self._on_progress)
        self._worker.finished_data.connect(self._on_finished)
        self._worker.start()

    def _cancel_optimization(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.terminate()
            self.status_label.setText("Optimization cancelled by user.")
            self.start_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)

    def _on_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        self.status_label.setText(msg)

    def _on_finished(self, success: bool, message: str, result_dict: dict | None):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

        if not success or result_dict is None:
            QMessageBox.critical(self, "Optimization Failed", message)
            self.status_label.setText(f"Error: {message}")
            return

        self._current_result = result_dict
        if result_dict.get("video_info"):
            self._video_info = result_dict.get("video_info")
        self.status_label.setText(message)
        self.save_btn.setEnabled(True)
        self.open_editor_btn.setEnabled(True)

        if result_dict.get("is_dynamic"):
            self._render_dynamic_results(result_dict)
            self.results_stack.setCurrentIndex(1)
        else:
            self._render_static_results(result_dict)
            self.results_stack.setCurrentIndex(2)

    def _render_dynamic_results(self, result: dict):
        raw_events = result["raw_events"]
        opt_events = result["optimized_events"]

        total_orig = len(raw_events)
        total_opt = len(opt_events)
        reduction_pct = ((total_orig - total_opt) / total_orig) * 100.0 if total_orig > 0 else 0.0

        dur_ticks = opt_events[-1]["end_time"] - opt_events[0]["start_time"]
        dur_tc = time_utils.ticks_to_timecode(dur_ticks)

        self.dynamic_summary.setText(
            f"Original: {total_orig:,} events  →  Optimized: {total_opt:,} scenes "
            f"({reduction_pct:.1f}% reduction)  |  Timeline Duration: {dur_tc}  |  Range: {'Full (0-255)' if result['is_full_range'] else 'Limited (16-235)'}"
        )

        from fgseditor_qt.core.settings_manager import get_setting

        fps = 0.0
        if getattr(self, "_video_info", None):
            fps = self._video_info.get("fps", 0.0)
        if fps <= 0:
            fps = time_utils.fps_from_label(get_setting("default_fps", time_utils.DEFAULT_FPS_LABEL))

        self.scenes_table.setRowCount(total_opt)

        for row, ev in enumerate(opt_events):
            t_start = ev["start_time"]
            t_end = ev["end_time"]
            tc_str = f"{time_utils.ticks_to_timecode(t_start)} - {time_utils.ticks_to_timecode(t_end)}"
            f_start = time_utils.ticks_to_frames(t_start, fps)
            f_end = time_utils.ticks_to_frames(t_end, fps)
            frames_str = f"{f_start} - {f_end} ({f_end - f_start})"

            merged_count = ev.get("raw_events_count", 1)
            strength = ev.get("apparent_strength", 0.0)
            cut_status = ev.get("cut_status", "[• Similarity Merge]")

            item_idx = QTableWidgetItem(f"Scene {row + 1}")
            item_tc = QTableWidgetItem(tc_str)
            item_frames = QTableWidgetItem(frames_str)
            item_merged = QTableWidgetItem(str(merged_count))
            item_strength = QTableWidgetItem(f"{strength:.2f}")
            item_status = QTableWidgetItem(cut_status)

            for item in (item_idx, item_tc, item_frames, item_merged, item_strength, item_status):
                item.setFlags(Qt.ItemIsEnabled)

            if "Video Scene Cut" in cut_status:
                item_status.setForeground(Qt.green)
            elif "Mid-Shot" in cut_status:
                item_status.setForeground(Qt.cyan)

            self.scenes_table.setItem(row, 0, item_idx)
            self.scenes_table.setItem(row, 1, item_tc)
            self.scenes_table.setItem(row, 2, item_frames)
            self.scenes_table.setItem(row, 3, item_merged)
            self.scenes_table.setItem(row, 4, item_strength)
            self.scenes_table.setItem(row, 5, item_status)

            act_item = QTableWidgetItem("")
            act_item.setFlags(Qt.NoItemFlags)
            self.scenes_table.setItem(row, 6, act_item)
            if ev.get("is_equivalent_with_prev") and row > 0:
                unify_btn = QPushButton("Merge with Prev")
                unify_btn.setStyleSheet(
                    "background-color: #3d5a80; color: white; padding: 3px 8px; border-radius: 3px; font-size: 11px; font-weight: bold;"
                )
                unify_btn.clicked.connect(lambda _, r=row: self._unify_scene_with_prev(r))
                self.scenes_table.setCellWidget(row, 6, unify_btn)
            else:
                self.scenes_table.setCellWidget(row, 6, None)

        self.scenes_table.resizeColumnsToContents()
        self.scenes_table.setColumnWidth(6, max(130, self.scenes_table.columnWidth(6)))

    def _unify_scene_with_prev(self, row: int):
        if not self._current_result or row <= 0:
            return

        opt_events = self._current_result["optimized_events"]
        raw_events = self._current_result["raw_events"]
        prev_ev = opt_events[row - 1]
        curr_ev = opt_events[row]

        t_start = prev_ev["start_time"]
        t_end = curr_ev["end_time"]
        raw_slice = fgs_optimizer.get_raw_events_in_range(raw_events, t_start, t_end) or [prev_ev, curr_ev]
        unified = fgs_optimizer.consolidate_raw_events(
            raw_slice,
            t_start,
            t_end,
            is_full_range=self._current_result["is_full_range"],
            ignore_chroma=self._current_result["ignore_chroma"],
            skip_simulation=False,
        )
        unified["apparent_strength"] = fgs_optimizer.evaluate_apparent_grain_strength(unified)
        unified["cut_status"] = prev_ev.get("cut_status", "[• Similarity Merge]")

        opt_events[row - 1] = unified
        opt_events.pop(row)

        self._render_dynamic_results(self._current_result)

    def _render_static_results(self, result: dict):
        orig_ev = result["original_event"]
        opt_ev = result["optimized_event"]
        safe_env = result["safe_envelope"]
        is_full = result["is_full_range"]

        orig_sd = orig_ev.get("scale_data") or {}
        opt_sd = opt_ev.get("scale_data") or {}

        orig_xs = orig_sd.get("sY", {}).get("x", [])
        orig_ys = orig_sd.get("sY", {}).get("y", [])
        opt_xs = opt_sd.get("sY", {}).get("x", [])
        opt_ys = opt_sd.get("sY", {}).get("y", [])

        orig_pts = len(orig_xs)
        opt_pts = len(opt_xs)

        self.static_summary.setText(
            f"Static FGS Profile: Original points: {orig_pts}  →  Optimized points: {opt_pts}  |  "
            f"Anti-Clipping Envelope Applied ({'Full Range' if is_full else 'Limited TV Range 16–235'})"
        )

        self.static_figure.clear()
        ax = self.static_figure.add_subplot(111)
        ax.set_facecolor("#141414")

        x_all = list(range(256))
        ax.plot(x_all, safe_env, label="Safe Envelope (Anti-Clipping)", color="#ffaa00", linestyle="--", linewidth=1.2, alpha=0.85)

        if orig_xs:
            ax.plot(orig_xs, orig_ys, label="Original Curve", color="#888888", linestyle=":", marker="o", markersize=4, alpha=0.7)

        if opt_xs:
            ax.plot(opt_xs, opt_ys, label="Optimized Safe Curve", color="#00ffcc", linewidth=2.0, marker="s", markersize=4)

        if not is_full:
            ax.axvline(16, color="#ff4444", linestyle="--", alpha=0.5, label="Legal Black (16)")
            ax.axvline(235, color="#ff4444", linestyle="--", alpha=0.5, label="Legal White (235)")

        ax.set_xlim(0, 255)
        ax.set_ylim(0, 260)
        ax.set_xlabel("Pixel Luminance (X)", color="#dddddd")
        ax.set_ylabel("Grain Amplitude / Scaling (Y)", color="#dddddd")
        ax.tick_params(colors="#aaaaaa")
        ax.grid(True, color="#2a2a2a", linestyle="--", alpha=0.6)
        ax.legend(facecolor="#222222", edgecolor="#444444", labelcolor="#dddddd", loc="upper right")

        self.static_figure.tight_layout()
        self.static_canvas.draw()

    def _save_optimized_fgs(self):
        if not self._current_result:
            return

        from fgseditor_qt.core.settings_manager import get_dialog_dir, update_dialog_dir

        if self.fgs_edit.text():
            base, ext = os.path.splitext(self.fgs_edit.text())
            default_name = f"{base}_optimized{ext if ext in ('.txt', '.tbl') else '.tbl'}"
        else:
            default_name = os.path.join(get_dialog_dir("last_fgs_dir"), "optimized_fgs.tbl")

        fpath, _ = QFileDialog.getSaveFileName(
            self, "Save Optimized FGS Table", default_name, "FGS Table (*.tbl *.txt);;All Files (*)"
        )
        if not fpath:
            return

        if self._current_result.get("is_dynamic"):
            text = fgs_optimizer.build_optimized_fgs_text(
                self._current_result["optimized_events"], self._current_result.get("headers")
            )
        else:
            text = fgs_optimizer.build_optimized_fgs_text(
                [self._current_result["optimized_event"]], self._current_result.get("headers")
            )

        tmp_path = fpath + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            os.replace(tmp_path, fpath)
            update_dialog_dir("last_fgs_dir", fpath)
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Could not save file:\n{e}")
            return False
        finally:
            if os.path.isfile(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        self._is_saved = True
        QMessageBox.information(self, "Saved", f"Optimized FGS saved to:\n{fpath}")
        return True

    def _open_in_editor(self):
        if not self._current_result:
            return

        self._is_saved = True
        self._opened_in_editor = True
        import tempfile
        import time
        tmp_dir = tempfile.gettempdir()
        tmp_path = os.path.join(tmp_dir, f".tmp_opt_{os.getpid()}_{int(time.time())}.tbl")
        self._tmp_path = tmp_path

        if self._current_result.get("is_dynamic"):
            text = fgs_optimizer.build_optimized_fgs_text(
                self._current_result["optimized_events"], self._current_result.get("headers")
            )
        else:
            text = fgs_optimizer.build_optimized_fgs_text(
                [self._current_result["optimized_event"]], self._current_result.get("headers")
            )

        with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

        self.fgs_loaded.emit(tmp_path)
        self.accept()

    def closeEvent(self, event):
        if not self.isVisible():
            event.accept()
            return

        if self._worker and self._worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Cancel Optimization?",
                "Optimization in progress.\nCancel and exit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._cancel_optimization()
                self._worker.wait(2000)
                event.accept()
            else:
                event.ignore()
                return

        if self._current_result and not getattr(self, "_is_saved", False):
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Unsaved Optimization")
            msg_box.setText(
                "Optimization results have not been saved or applied to the editor.\n\n"
                "What would you like to do before closing?"
            )
            apply_btn = msg_box.addButton("Apply to Editor", QMessageBox.AcceptRole)
            save_btn = msg_box.addButton("Save to File", QMessageBox.ActionRole)
            discard_btn = msg_box.addButton("Discard", QMessageBox.DestructiveRole)
            cancel_btn = msg_box.addButton("Cancel", QMessageBox.RejectRole)
            msg_box.setDefaultButton(apply_btn)

            msg_box.exec()
            clicked = msg_box.clickedButton()

            if clicked == apply_btn:
                self._open_in_editor()
                event.accept()
            elif clicked == save_btn:
                saved = self._save_optimized_fgs()
                if saved or getattr(self, "_is_saved", False):
                    event.accept()
                else:
                    event.ignore()
                    return
            elif clicked == discard_btn:
                event.accept()
            else:
                event.ignore()
                return
        else:
            event.accept()

        if event.isAccepted():
            if not getattr(self, "_opened_in_editor", False):
                tmp_p = getattr(self, "_tmp_path", None)
                if tmp_p and os.path.isfile(tmp_p):
                    try:
                        os.remove(tmp_p)
                    except OSError:
                        pass
            if hasattr(self, "static_figure") and self.static_figure is not None:
                import matplotlib.pyplot as plt
                try:
                    plt.close(self.static_figure)
                except Exception:
                    pass
                self.static_figure = None
            if hasattr(self, "static_canvas") and self.static_canvas is not None:
                self.static_canvas.deleteLater()
                self.static_canvas = None

    def reject(self):
        self.close()

