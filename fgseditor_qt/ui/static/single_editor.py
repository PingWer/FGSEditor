from __future__ import annotations
import copy
from collections import deque
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QComboBox,
    QFrame,
    QSizePolicy,
    QSplitter,
    QDialog,
    QCheckBox,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QSpinBox,
)
import os
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QShortcut, QKeySequence

from fgseditor_qt.core import fgs_parser
from fgseditor_qt.math import fgs_math
from fgseditor_qt.math.time_utils import ticks_to_seconds, ticks_to_frames, ticks_to_timecode

from fgseditor_qt.ui.widgets.plotter import InteractiveFGSPlotter
from fgseditor_qt.ui.widgets.grain_preview import GrainPreviewPlotter
from fgseditor_qt.ui.widgets.params_sidebar import ParamsSidebar
from fgseditor_qt.ui.panels.tabs_widget import SettingsTabsBar


class SingleEventEditor(QWidget):
    save_event_requested = Signal()
    cancel_requested = Signal()

    close_fgs_requested = Signal()
    save_fgs_requested = Signal()
    save_bin_requested = Signal()
    save_apply_requested = Signal()
    save_plot_requested = Signal()
    
    state_changed = Signal(bool)

    def __init__(self, is_dynamic=False, parent=None):
        super().__init__(parent)
        self.is_dynamic = is_dynamic
        
        self.event_dict = None
        self.event_idx = -1
        self._working = {}
        
        self.current_scale_data = {}
        self.original_scale_data = {}
        self.original_p_params = {}
        self.original_grain_size = "-1"
        self.original_time_bounds = (0, 0)
        self._ar_windows = {"Y": None, "Cb": None, "Cr": None}
        self.original_ar_coeffs = {"Y": [], "Cb": [], "Cr": []}
        self._has_sanitization_changes = False

        from fgseditor_qt.core.settings_manager import get_setting
        undo_size = get_setting("undo_stack_size", 100)
        self._undo_stack = deque(maxlen=undo_size)
        self._redo_stack = deque(maxlen=undo_size)
        self._last_known_state = None
        
        self.fps_callback = None

        self._setup_ui()

    def _setup_ui(self):
        if not self.is_dynamic:
            self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.top_frame = QFrame()
        self.top_frame.setObjectName("toolbar")
        top_layout = QHBoxLayout(self.top_frame)
        top_layout.setContentsMargins(10, 6, 10, 6)

        self.close_btn = QPushButton("Close FGS")
        self.close_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.close_btn.clicked.connect(self.close_fgs_requested.emit)
        top_layout.addWidget(self.close_btn, stretch=0)

        self.file_label = QLabel("No file selected")
        self.file_label.setWordWrap(True)
        top_layout.addWidget(self.file_label, stretch=1)
        
        if not self.is_dynamic:
            layout.addWidget(self.top_frame)
        else:
            self.top_frame.hide()

        self.mid_frame = QFrame()
        self.mid_frame.setObjectName("toolbar")
        mid_layout = QHBoxLayout(self.mid_frame)
        mid_layout.setContentsMargins(10, 4, 10, 4)

        mid_layout.addWidget(QLabel("Channel:"), stretch=0)
        self.channel_dropdown = QComboBox()
        self.channel_dropdown.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.channel_dropdown.addItems(["sY", "sCb", "sCr"])
        self.channel_dropdown.currentTextChanged.connect(self.on_channel_change)
        mid_layout.addWidget(self.channel_dropdown, stretch=0)

        self.full_range_cb = QCheckBox("Full Range (0–255)")
        self.full_range_cb.setToolTip("Toggle limited (16–235) or full (0–255) range.")
        self.full_range_cb.toggled.connect(self._on_full_range_toggled)
        mid_layout.addWidget(self.full_range_cb, stretch=0)

        mid_layout.addStretch(1)
        
        self.time_info_label = QLabel()
        self.time_info_label.setStyleSheet(
            "color: #4da6ff; font-size: 12px; font-family: monospace;"
        )
        self.time_info_label.setToolTip("Event time range and frames.")
        mid_layout.addWidget(self.time_info_label, stretch=0)
        if not self.is_dynamic:
            self.time_info_label.hide()

        self.validation_warning_label = QLabel()
        self.validation_warning_label.setStyleSheet(
            "color: #ff4444; font-weight: bold; background: #220000; padding: 2px 6px; border-radius: 4px;"
        )
        self.validation_warning_label.hide()
        mid_layout.addWidget(self.validation_warning_label)

        self.save_event_btn = QPushButton("Save Event")
        self.save_event_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.save_event_btn.clicked.connect(self.save_event_requested.emit)
        self.save_event_btn.setEnabled(False)
        mid_layout.addWidget(self.save_event_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        mid_layout.addWidget(self.cancel_btn)

        self.save_fgs_btn = QPushButton("Save FGS")
        self.save_fgs_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.save_fgs_btn.clicked.connect(self.save_fgs_requested.emit)
        self.save_fgs_btn.setEnabled(False)
        mid_layout.addWidget(self.save_fgs_btn)

        self.save_bin_btn = QPushButton("Save Binary")
        self.save_bin_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.save_bin_btn.clicked.connect(self.save_bin_requested.emit)
        self.save_bin_btn.setEnabled(False)
        mid_layout.addWidget(self.save_bin_btn)

        self.save_apply_btn = QPushButton("Save && Apply")
        self.save_apply_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.save_apply_btn.clicked.connect(self.save_apply_requested.emit)
        self.save_apply_btn.setEnabled(False)
        self.save_apply_btn.setVisible(False)
        mid_layout.addWidget(self.save_apply_btn)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.reset_btn.clicked.connect(self.reset_data)
        self.reset_btn.setEnabled(False)
        mid_layout.addWidget(self.reset_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.clear_btn.clicked.connect(self.clear_channel)
        self.clear_btn.setEnabled(False)
        mid_layout.addWidget(self.clear_btn)

        self.save_plot_btn = QPushButton("Save Plot")
        self.save_plot_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.save_plot_btn.clicked.connect(self.save_plot_requested.emit)
        mid_layout.addWidget(self.save_plot_btn)

        if self.is_dynamic:
            self.save_fgs_btn.hide()
            self.save_bin_btn.hide()
            self.save_apply_btn.hide()
            self.reset_btn.hide()
            self.clear_btn.hide()
            self.save_plot_btn.hide()
        else:
            self.save_event_btn.hide()
            self.cancel_btn.hide()

        layout.addWidget(self.mid_frame)

        self.tabs_bar = SettingsTabsBar()
        self.tabs_bar.ar_buttons["Y"].clicked.connect(lambda: self.open_ar_editor("Y"))
        self.tabs_bar.ar_buttons["Cb"].clicked.connect(lambda: self.open_ar_editor("Cb"))
        self.tabs_bar.ar_buttons["Cr"].clicked.connect(lambda: self.open_ar_editor("Cr"))
        layout.addWidget(self.tabs_bar)

        h_splitter = QSplitter(Qt.Horizontal)
        h_splitter.setHandleWidth(4)
        h_splitter.setStyleSheet("QSplitter::handle { background: #333355; }")
        layout.addWidget(h_splitter, stretch=1)

        self.sidebar = ParamsSidebar()
        self.tabs_bar.tab_changed.connect(self.sidebar.set_tab)
        self.sidebar.params_changed.connect(self._on_params_changed)
        self.sidebar.grain_size_changed.connect(self._on_grain_size_changed)
        self.sidebar.photon_noise_changed.connect(self._on_photon_noise_changed)
        self.sidebar.template_apply_requested.connect(self._on_template_apply_requested)
        self.sidebar.time_changed.connect(self._on_time_changed)
        self.sidebar.fps_or_mode_changed.connect(self._on_fps_or_mode_changed)
        h_splitter.addWidget(self.sidebar)

        v_splitter = QSplitter(Qt.Vertical)
        v_splitter.setHandleWidth(4)
        v_splitter.setStyleSheet("QSplitter::handle { background: #333355; }")
        h_splitter.addWidget(v_splitter)

        self.plotter = InteractiveFGSPlotter()
        self.plotter.undo_push_requested.connect(self._on_plotter_undo_push_requested)
        self.plotter.undo_requested.connect(self.undo)
        self.plotter.redo_requested.connect(self.redo)
        self.plotter.data_changed.connect(self.on_plotter_changed)
        v_splitter.addWidget(self.plotter)

        from PySide6.QtGui import QShortcut, QKeySequence
        self.undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self.undo_shortcut.activated.connect(self.undo)
        self.redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        self.redo_shortcut.activated.connect(self.redo)

        self.grain_preview = GrainPreviewPlotter()
        self.grain_preview.setMinimumHeight(130)
        v_splitter.addWidget(self.grain_preview)

        v_splitter.setSizes([420, 220])
        h_splitter.setSizes([320, 680] if not self.is_dynamic else [200, 800])

        self.original_p_params = self.sidebar.get_p_params()
        self.original_grain_size = self.sidebar.get_grain_size()
        self.original_time_bounds = self.sidebar.get_event_time_bounds()

    def set_has_sanitization_changes(self, changed: bool):
        self._has_sanitization_changes = changed
        self._update_ui_state()

    def load_event(self, event_dict, event_idx=-1):
        self._has_sanitization_changes = False
        self.close_ar_windows()
        if not event_dict:
            self._working = {}
            self.event_dict = None
            self.event_idx = -1
            self.original_scale_data = {}
            self.current_scale_data = {}
            self.original_p_params = self.sidebar.get_p_params()
            self.original_grain_size = self.sidebar.get_grain_size()
            self.original_time_bounds = self.sidebar.get_event_time_bounds()
            self.original_ar_coeffs = {"Y": [], "Cb": [], "Cr": []}
            self._has_sanitization_changes = False
            self._is_temp = False
            self.reset_btn.setEnabled(False)
            self.clear_btn.setEnabled(False)
            self.plotter.set_data({})
            self._refresh_time_info()
            self._refresh_grain_preview()
            self._update_ui_state()
            self._update_last_known_state()
            return

        self.event_dict = event_dict
        self.event_idx = event_idx
        self._working = copy.deepcopy(event_dict)

        self.original_scale_data = copy.deepcopy(
            self._working.get("scale_data") or fgs_parser.get_scale_data(self._working)
        )
        self.current_scale_data = copy.deepcopy(self.original_scale_data)
        
        has_full_range = False
        if self.current_scale_data:
            for ch_data in self.current_scale_data.values():
                for px in ch_data.get("x", []):
                    if px < 16 or px > 235:
                        has_full_range = True
                        break
                if has_full_range:
                    break
        self.full_range_cb.blockSignals(True)
        self.full_range_cb.setChecked(has_full_range)
        self.full_range_cb.blockSignals(False)
        self.plotter.set_full_range_mode(has_full_range)
        self.plotter.set_data(self.current_scale_data)

        if self._working:
            self.sidebar.load_from_event(self._working, size_id="-1")
            start_t = self._working.get("start_time", 0)
            end_t = self._working.get("end_time", 0)
            if start_t > 0 or end_t > 0:
                self.sidebar.set_event_times(start_t, end_t)

        self.original_p_params = self.sidebar.get_p_params()
        self.original_grain_size = self.sidebar.get_grain_size()
        self.original_time_bounds = self.sidebar.get_event_time_bounds()

        orig_cy, orig_cb, orig_cr = fgs_parser.extract_ar_coeffs_from_raw_lines(
            self._working.get("raw_lines", [])
        )
        self.original_ar_coeffs = {
            "Y": orig_cy,
            "Cb": orig_cb,
            "Cr": orig_cr,
        }

        self.reset_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)

        self._refresh_time_info()
        self._refresh_grain_preview()
        self._update_ui_state()
        self._update_last_known_state()

    def set_time_limits(self, min_t, max_t):
        self.sidebar.set_time_limits(min_t, max_t)

    def set_times(self, start_ticks: int, end_ticks: int) -> None:
        if self._working:
            self._working["start_time"] = start_ticks
            self._working["end_time"] = end_ticks
        if self.event_dict:
            self.event_dict["start_time"] = start_ticks
            self.event_dict["end_time"] = end_ticks
        self.sidebar.set_event_times(start_ticks, end_ticks)
        self._refresh_time_info()

    def set_video_info(self, info):
        self.sidebar.set_video_info(info)

    def set_file_label(self, text):
        self.file_label.setText(text)
        
    def set_save_apply_enabled(self, enabled, tooltip=""):
        self.save_apply_btn.setVisible(True)
        self.save_apply_btn.setEnabled(enabled)
        if tooltip:
            self.save_apply_btn.setToolTip(tooltip)
            
    def set_save_bin_enabled(self, enabled):
        self.save_bin_btn.setEnabled(enabled)

    def close_plotters(self):
        self.close_ar_windows()
        if self.plotter:
            self.plotter.close_plot()

    def open_ar_editor(self, channel: str):
        if not self._working:
            return

        if self._ar_windows.get(channel) is not None:
            self._ar_windows[channel].activateWindow()
            self._ar_windows[channel].raise_()
            return

        win = ARCoefficientsEditor(channel, self, self.window())
        self._ar_windows[channel] = win
        win.show()

    def has_open_ar_windows(self) -> bool:
        return any(win is not None for win in self._ar_windows.values())

    def close_ar_windows(self):
        for ch, win in list(self._ar_windows.items()):
            if win is not None:
                try:
                    win.close()
                except Exception:
                    pass
        self._ar_windows = {"Y": None, "Cb": None, "Cr": None}

    def update_ar_coeffs(self, channel: str, coeffs: list[int]):
        if not self._working:
            return

        lag = self.sidebar.get_p_params().get("ar_coeff_lag", 3)

        prefix = "cY" if channel == "Y" else ("cCb" if channel == "Cb" else "cCr")
        new_line = fgs_parser.format_c_line(prefix, coeffs, lag)

        raw_lines = self._working.get("raw_lines", [])
        aliases = (
            ("cY", "Y", "cy", "y", "CY")
            if prefix == "cY"
            else (("cCb", "Cb", "ccb", "cb", "CCb", "CB") if prefix == "cCb" else ("cCr", "Cr", "ccr", "cr", "CCr", "CR"))
        )
        new_raw_lines = []
        updated = False
        for line in raw_lines:
            clean = line.split("#", 1)[0].strip()
            tokens = clean.split()
            if tokens and tokens[0] in aliases:
                if not updated:
                    new_raw_lines.append(new_line)
                    updated = True
            else:
                new_raw_lines.append(line)
        if not updated:
            new_raw_lines.append(new_line)
        self._working["raw_lines"] = new_raw_lines

        self._refresh_grain_preview()
        self._update_ui_state()

    def get_working_event(self):
        self._working["scale_data"] = copy.deepcopy(self.current_scale_data)
        self._working["p_params"] = self.sidebar.get_p_params()
        self._working["grain_size"] = self.sidebar.get_grain_size()
        st, et = self.sidebar.get_event_time_bounds()
        self._working["start_time"] = st
        self._working["end_time"] = et
        return self._working

    def apply_working_to_event(self):
        if self.event_dict is not None:
            working = self.get_working_event()
            self.event_dict.update(working)
            
            self.original_scale_data = copy.deepcopy(self.current_scale_data)
            self.original_p_params = self.sidebar.get_p_params()
            self.original_grain_size = self.sidebar.get_grain_size()
            self.original_time_bounds = self.sidebar.get_event_time_bounds()
            orig_cy, orig_cb, orig_cr = fgs_parser.extract_ar_coeffs_from_raw_lines(
                self._working.get("raw_lines", [])
            )
            self.original_ar_coeffs = {
                "Y": orig_cy,
                "Cb": orig_cb,
                "Cr": orig_cr,
            }
            self._update_ui_state()

    def _refresh_time_info(self):
        if not self.is_dynamic or not self._working:
            return
            
        start_ticks = self._working.get("start_time", 0)
        end_ticks = self._working.get("end_time", 0)
        start_s = ticks_to_seconds(start_ticks)
        end_s = ticks_to_seconds(end_ticks)
        start_tc = ticks_to_timecode(start_ticks)
        end_tc = ticks_to_timecode(end_ticks)

        fps, fps_label = None, ""
        if self.fps_callback:
            fps, fps_label = self.fps_callback()

        if fps:
            start_f = ticks_to_frames(start_ticks, fps)
            end_f = ticks_to_frames(end_ticks, fps)
            self.time_info_label.setText(
                f"⏱ {start_tc}  ({start_s:.4f}s)  →  {end_tc}  ({end_s:.4f}s)"
                f"   │   🎞 frame {start_f} → {end_f}  @ {fps_label} fps"
            )
        else:
            self.time_info_label.setText(
                f"⏱ {start_tc}  ({start_s:.4f}s)  →  {end_tc}  ({end_s:.4f}s)"
            )

    def _on_full_range_toggled(self, checked: bool):
        if self.plotter:
            self.plotter.set_full_range_mode(checked)

    def on_channel_change(self, text):
        self.plotter.active_channel = text
        self._update_plot_x_label()
        self.plotter.refresh()

    def on_plotter_changed(self):
        self.current_scale_data = {
            ch: {"x": list(d.get("x", [])), "y": list(d.get("y", []))}
            for ch, d in self.plotter.current_data.items()
        }
        self._sync_chromas_if_needed()
        self._refresh_grain_preview()
        self._update_ui_state()
        self._update_last_known_state()

    def _sync_chromas_if_needed(self):
        p_params = self.sidebar.get_p_params()
        linked = bool(p_params.get("chroma_scaling_from_luma", 0))

        self.plotter.set_chroma_linked(linked)

        if linked:
            self.current_scale_data["sCb"] = {"x": [], "y": []}
            self.current_scale_data["sCr"] = {"x": [], "y": []}

            self.plotter.current_data = {
                ch: {"x": list(d.get("x", [])), "y": list(d.get("y", []))}
                for ch, d in self.current_scale_data.items()
            }
            self.plotter.refresh()

    def _on_params_changed(self, p_params: dict):
        self._push_undo_global()
        self._working["p_params"] = p_params
        
        self._sync_chromas_if_needed()
        
        for win in self._ar_windows.values():
            if win is not None:
                win.refresh_table()
            
        self._refresh_grain_preview(p_params=p_params)
        self._update_ui_state()
        self._update_last_known_state()

    def _on_grain_size_changed(self, size: str):
        self._push_undo_global()
        from fgseditor_qt.core.fgs_size_table import apply_grain_preset_to_event
        apply_grain_preset_to_event(self._working, size)
        self.sidebar.load_from_event(self._working, size_id=size)

        updated_scale_data = self._working.get(
            "scale_data",
            {"sY": {"x": [], "y": []}, "sCb": {"x": [], "y": []}, "sCr": {"x": [], "y": []}},
        )
        self.current_scale_data = copy.deepcopy(updated_scale_data)
        self.plotter.set_data(self.current_scale_data)

        for win in self._ar_windows.values():
            if win is not None:
                win.refresh_table()

        self._refresh_grain_preview(grain_size=size)
        self._update_ui_state()
        self._update_last_known_state()

    def _on_photon_noise_changed(self, payload: dict):
        if not self.current_scale_data:
            return

        if (self.current_scale_data["sY"]["x"] == payload["sY"]["x"]
            and self.current_scale_data["sY"]["y"] == payload["sY"]["y"]):
            return

        self._push_undo_global()
        self.current_scale_data["sY"]["x"] = payload["sY"]["x"]
        self.current_scale_data["sY"]["y"] = payload["sY"]["y"]

        if payload.get("sCb", {}).get("x"):
            self.current_scale_data["sCb"]["x"] = payload["sCb"]["x"]
            self.current_scale_data["sCb"]["y"] = payload["sCb"]["y"]
            self.current_scale_data["sCr"]["x"] = payload["sCr"]["x"]
            self.current_scale_data["sCr"]["y"] = payload["sCr"]["y"]

        self.plotter.current_data = copy.deepcopy(self.current_scale_data)
        self.plotter.refresh()
        self._refresh_grain_preview()
        self._update_ui_state()
        self._update_last_known_state()

    def _on_template_apply_requested(self, template_evt: dict, mode: int):
        self._push_undo_global()

        if mode in (0, 1):
            if "scale_data" in template_evt and template_evt["scale_data"]:
                for ch in ["sY", "sCb", "sCr"]:
                    if ch in template_evt["scale_data"]:
                        self.current_scale_data[ch] = copy.deepcopy(template_evt["scale_data"][ch])

        if mode in (0, 2):
            new_lines = []
            tmpl_lines_map = {}
            for line in template_evt.get("raw_lines", []):
                clean = line.split("#", 1)[0].strip()
                tokens = clean.split()
                if not tokens:
                    continue
                t0_lower = tokens[0].lower()
                if t0_lower in ("cy", "y"):
                    tmpl_lines_map["cY"] = line
                elif t0_lower in ("ccb", "cb"):
                    tmpl_lines_map["cCb"] = line
                elif t0_lower in ("ccr", "cr"):
                    tmpl_lines_map["cCr"] = line

            c_handled = set()
            for line in self._working.get("raw_lines", []):
                clean = line.split("#", 1)[0].strip()
                tokens = clean.split()
                if not tokens:
                    new_lines.append(line)
                    continue
                t0_lower = tokens[0].lower()
                c_key = None
                if t0_lower in ("cy", "y"):
                    c_key = "cY"
                elif t0_lower in ("ccb", "cb"):
                    c_key = "cCb"
                elif t0_lower in ("ccr", "cr"):
                    c_key = "cCr"

                if c_key:
                    if c_key in tmpl_lines_map:
                        if c_key not in c_handled:
                            new_lines.append(tmpl_lines_map[c_key])
                            c_handled.add(c_key)
                    else:
                        if c_key not in c_handled:
                            new_lines.append(line)
                            c_handled.add(c_key)
                else:
                    new_lines.append(line)

            for k, val in tmpl_lines_map.items():
                if k not in c_handled:
                    new_lines.append(val)
            self._working["raw_lines"] = new_lines

        if mode == 2:
            tmpl_p = template_evt.get("p_params")
            if tmpl_p:
                if "p_params" not in self._working or self._working["p_params"] is None:
                    self._working["p_params"] = {}
                self._working["p_params"]["ar_coeff_lag"] = tmpl_p.get("ar_coeff_lag", 3)
                self._working["p_params"]["ar_coeff_shift"] = tmpl_p.get("ar_coeff_shift", 8)

        if mode == 0:
            if template_evt.get("p_params"):
                self._working["p_params"] = copy.deepcopy(template_evt["p_params"])

        self.sidebar.load_from_event(self._working, size_id="-1")
        self.plotter.current_data = copy.deepcopy(self.current_scale_data)
        self.plotter.refresh()
        self._refresh_grain_preview()
        self._update_ui_state()
        self._update_last_known_state()

    def _on_time_changed(self, start: int, end: int):
        self._push_undo_global()
        self._working["start_time"] = start
        self._working["end_time"] = end
        self._refresh_time_info()
        self._update_ui_state()
        self._update_last_known_state()

    def _on_fps_or_mode_changed(self):
        self._push_undo_global()
        self._refresh_time_info()
        self._update_ui_state()
        self._update_last_known_state()

    def _update_last_known_state(self):
        self._last_known_state = {
            "data": copy.deepcopy(self.current_scale_data),
            "sidebar": self.sidebar.get_full_state(),
            "working": copy.deepcopy(self._working),
        }

    def _push_undo_global(self, override_data=None):
        if not self._last_known_state:
            return

        state_to_push = copy.deepcopy(self._last_known_state)
        if override_data is not None:
            state_to_push["data"] = copy.deepcopy(override_data)

        self._undo_stack.append(state_to_push)
        self._redo_stack.clear()

    def _on_plotter_undo_push_requested(self, override_data):
        self._push_undo_global(override_data)

    def _preserve_and_apply_ar_coeffs(self, action_func):
        cy, cb, cr = fgs_parser.extract_ar_coeffs_from_raw_lines(
            self._working.get("raw_lines", [])
        )
        
        action_func()
        
        if self._working:
            lag = self.sidebar.get_p_params().get("ar_coeff_lag", 3)
            
            for channel, prefix, coeffs in [
                ("Y", "cY", cy),
                ("Cb", "cCb", cb),
                ("Cr", "cCr", cr),
            ]:
                new_line = fgs_parser.format_c_line(prefix, coeffs, lag)
                raw_lines = self._working.get("raw_lines", [])
                aliases = (
                    ("cY", "Y", "cy", "y", "CY")
                    if prefix == "cY"
                    else (("cCb", "Cb", "ccb", "cb", "CCb", "CB") if prefix == "cCb" else ("cCr", "Cr", "ccr", "cr", "CCr", "CR"))
                )
                new_raw_lines = []
                updated = False
                for line in raw_lines:
                    clean = line.split("#", 1)[0].strip()
                    tokens = clean.split()
                    if tokens and tokens[0] in aliases:
                        if not updated:
                            new_raw_lines.append(new_line)
                            updated = True
                    else:
                        new_raw_lines.append(line)
                if not updated:
                    new_raw_lines.append(new_line)
                self._working["raw_lines"] = new_raw_lines
                
            for win in self._ar_windows.values():
                if win is not None:
                    win.refresh_table()
                    
            self._refresh_grain_preview()
            self._update_ui_state()
            self._update_last_known_state()

    def _sync_full_range_checkbox(self):
        has_full_range = any(
            px < 16 or px > 235
            for ch_data in self.current_scale_data.values()
            for px in ch_data.get("x", [])
        )
        if has_full_range and not self.full_range_cb.isChecked():
            self.full_range_cb.blockSignals(True)
            self.full_range_cb.setChecked(True)
            self.full_range_cb.blockSignals(False)
            self.plotter.set_full_range_mode(True)

    def undo(self):
        if not self._undo_stack or not self._last_known_state:
            return
        
        def do_undo():
            self._redo_stack.append(copy.deepcopy(self._last_known_state))
            state = self._undo_stack.pop()
            self.current_scale_data = copy.deepcopy(state["data"])
            self._working = copy.deepcopy(state.get("working", self._working))
            self.sidebar.set_full_state(state["sidebar"])
            
            self._sync_full_range_checkbox()
            self.plotter.current_data = copy.deepcopy(self.current_scale_data)
            self.plotter.refresh()
            self._refresh_time_info()

        self._preserve_and_apply_ar_coeffs(do_undo)

    def redo(self):
        if not self._redo_stack or not self._last_known_state:
            return
            
        def do_redo():
            self._undo_stack.append(copy.deepcopy(self._last_known_state))
            state = self._redo_stack.pop()
            self.current_scale_data = copy.deepcopy(state["data"])
            self._working = copy.deepcopy(state.get("working", self._working))
            self.sidebar.set_full_state(state["sidebar"])
            
            self._sync_full_range_checkbox()
            self.plotter.current_data = copy.deepcopy(self.current_scale_data)
            self.plotter.refresh()
            self._refresh_time_info()

        self._preserve_and_apply_ar_coeffs(do_redo)

    def reset_data(self):
        if not self.original_scale_data:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Reset",
            "Revert all changes?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._push_undo_global()
            self.current_scale_data = copy.deepcopy(self.original_scale_data)
            orig_full = any(
                px < 16 or px > 235
                for ch_data in self.original_scale_data.values()
                for px in ch_data.get("x", [])
            )
            self.full_range_cb.blockSignals(True)
            self.full_range_cb.setChecked(orig_full)
            self.full_range_cb.blockSignals(False)
            self.plotter.set_full_range_mode(orig_full)
            self.plotter.current_data = copy.deepcopy(self.current_scale_data)
            self.plotter.refresh()
            self._refresh_grain_preview()
            self._update_last_known_state()
            self._update_ui_state()

    def clear_channel(self):
        if not self.current_scale_data:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Clear Channels")
        dialog.setMinimumWidth(320)
        dialog.resize(320, 220)
        dialog.setStyleSheet("background-color: #1a1a2e; color: #dddddd;")

        vbox = QVBoxLayout(dialog)
        vbox.setContentsMargins(16, 16, 16, 16)
        vbox.setSpacing(12)

        lbl = QLabel("Channels to clear:")
        lbl.setStyleSheet("font-weight: bold; font-size: 13px; color: #4da6ff;")
        vbox.addWidget(lbl)

        chk_y = QCheckBox("Luma (sY)")
        chk_cb = QCheckBox("Chroma (sCb)")
        chk_cr = QCheckBox("Chroma (sCr)")

        chk_style = "QCheckBox { font-size: 12px; } QCheckBox::indicator { width: 16px; height: 16px; }"
        for chk in [chk_y, chk_cb, chk_cr]:
            chk.setStyleSheet(chk_style)

        act = self.channel_dropdown.currentText()
        if act == "sY":
            chk_y.setChecked(True)
        elif act == "sCb":
            chk_cb.setChecked(True)
        elif act == "sCr":
            chk_cr.setChecked(True)

        vbox.addWidget(chk_y)
        vbox.addWidget(chk_cb)
        vbox.addWidget(chk_cr)
        vbox.addSpacing(10)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        clear_btn = QPushButton("Clear Selected")
        clear_btn.setObjectName("clearBtn")
        clear_btn.setStyleSheet(
            "QPushButton { background: #5c1a1a; color: #ff6b6b; border: 1px solid #ff4444; border-radius: 4px; padding: 6px 14px; font-weight: bold; min-width: 100px; }"
            "QPushButton:hover { background: #7c2a2a; }"
        )

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            "QPushButton { background: #2d2d2d; color: #aaaaaa; border: 1px solid #444; border-radius: 4px; padding: 6px 14px; min-width: 80px; }"
            "QPushButton:hover { background: #3d3d3d; }"
        )

        btn_layout.addWidget(clear_btn)
        btn_layout.addWidget(cancel_btn)
        vbox.addLayout(btn_layout)

        clear_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)

        if dialog.exec() == QDialog.Accepted:
            selected = []
            if chk_y.isChecked():
                selected.append("sY")
            if chk_cb.isChecked():
                selected.append("sCb")
            if chk_cr.isChecked():
                selected.append("sCr")

            if not selected:
                return

            self._push_undo_global()
            for ch in selected:
                self.current_scale_data[ch]["x"] = []
                self.current_scale_data[ch]["y"] = []

            self.plotter.current_data = copy.deepcopy(self.current_scale_data)
            self.plotter.refresh()
            self._refresh_grain_preview()
            self._update_last_known_state()
            self._update_ui_state()

    def is_dirty(self) -> bool:
        if not self._working or self.event_dict is None:
            return False
        if getattr(self, "_has_sanitization_changes", False):
            return True
        if getattr(self, "_is_temp", False):
            return True
        if self.current_scale_data != self.original_scale_data:
            return True
        if self.sidebar.get_p_params() != self.original_p_params:
            return True
        if self.sidebar.get_grain_size() != self.original_grain_size:
            return True
        if self.sidebar.get_event_time_bounds() != self.original_time_bounds:
            return True
        if self._working:
            cy, cb, cr = fgs_parser.extract_ar_coeffs_from_raw_lines(
                self._working.get("raw_lines", [])
            )
            if {
                "Y": cy,
                "Cb": cb,
                "Cr": cr,
            } != self.original_ar_coeffs:
                return True
        return False

    def get_validation_errors(self) -> list[str]:
        if not self._working:
            return []

        p_params = self.sidebar.get_p_params()
        
        ar_shift = fgs_parser.get_ar_coeff_shift({"p_params": p_params})
        ar_lag = fgs_parser.get_ar_coeff_lag({"p_params": p_params})
            
        pure_ar_count = 2 * ar_lag * (ar_lag + 1)

        cy_coeffs, cb_coeffs, cr_coeffs = fgs_parser.extract_ar_coeffs_from_raw_lines(
            self._working.get("raw_lines", [])
        )

        all_errors = []
        chroma_from_luma = p_params.get("chroma_scaling_from_luma", 0) == 1
        for ch, coeffs, ch_key in [
            ("Y", cy_coeffs, "sY"),
            ("Cb", cb_coeffs, "sCb"),
            ("Cr", cr_coeffs, "sCr"),
        ]:
            if chroma_from_luma and ch in ("Cb", "Cr"):
                continue
                
            data = self.current_scale_data.get(ch_key, {})
            xs = data.get("x", [])
            ys = data.get("y", [])

            max_pts = 14 if ch == "Y" else 10
            if len(xs) > max_pts:
                all_errors.append(f"Channel {ch}: Max {max_pts} scaling points allowed ({len(xs)}).")
            if len(xs) == 1:
                all_errors.append(f"Channel {ch}: Must have 0 or >=2 points.")

            ar_coeffs = coeffs[:pure_ar_count] if ch in ("Cb", "Cr") else coeffs
            errors = fgs_math.validate_fgs_pipeline(ar_coeffs, ar_shift, ys)
            if errors:
                all_errors.append(f"Channel {ch}:\n" + "\n".join(" - " + e for e in errors))

        return all_errors

    def _update_ui_state(self):
        dirty = self.is_dirty()

        errors = self.get_validation_errors()
        if errors:
            self.validation_warning_label.setText("⚠ UNSAFE PRESET")
            self.validation_warning_label.setToolTip("\n\n".join(errors))
            self.validation_warning_label.show()
        else:
            self.validation_warning_label.hide()

        self.save_event_btn.setEnabled(dirty)
        self.save_fgs_btn.setEnabled(self._working is not None)
        
        self.state_changed.emit(dirty)

    def dragEnterEvent(self, event):
        if not self.is_dynamic and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if self.is_dynamic:
            return
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            filepath = urls[0].toLocalFile()
            event.acceptProposedAction()
            ext = os.path.splitext(filepath)[1].lower()
            win = self.window()
            if ext in (".txt", ".tbl") and hasattr(win, "load_file_from_path"):
                QTimer.singleShot(0, lambda p=filepath: win.load_file_from_path(p))
            elif ext in (
                ".mkv",
                ".ivf",
                ".hevc",
                ".avi",
                ".mov",
                ".webm",
                ".ts",
                ".flv",
                ".mp4",
            ) and hasattr(win, "load_video"):
                QTimer.singleShot(0, lambda p=filepath: win.load_video(p))

    def _refresh_grain_preview(self, p_params=None, grain_size=None):
        if p_params is None:
            p_params = self.sidebar.get_p_params()
        if grain_size is None:
            grain_size = self.sidebar.get_grain_size()

        seed = self.sidebar.get_seed()

        cy_coeffs, cb_coeffs, cr_coeffs = [], [], []
        if self._working:
            cy_coeffs, cb_coeffs, cr_coeffs = fgs_parser.extract_ar_coeffs_from_raw_lines(
                self._working.get("raw_lines", [])
            )

        self.grain_preview.update_preview(
            self.current_scale_data,
            p_params=p_params,
            grain_size=grain_size,
            cy_coeffs=cy_coeffs,
            cb_coeffs=cb_coeffs,
            cr_coeffs=cr_coeffs,
            seed=seed,
        )
        self.sidebar.set_ar_shift_warning(self.grain_preview.is_ar_unstable())

        extremes = getattr(self.grain_preview, "_last_extremes", None)
        scaling_shift = fgs_parser.get_scaling_shift({"p_params": p_params})
        if self.plotter:
            self.plotter.set_clip_extremes(extremes, scaling_shift)
            self._update_plot_x_label(p_params)
            self.plotter.refresh()

    def _update_plot_x_label(self, p_params=None):
        if not self.plotter:
            return
        if p_params is None:
            p_params = self.sidebar.get_p_params()

        channel = self.plotter.active_channel
        if channel == "sY":
            label = "Y Value"
        else:
            if p_params.get("chroma_scaling_from_luma", 0) == 1:
                label = "Derived from luma value"
            else:
                is_cb = channel == "sCb"
                mult = p_params.get("cb_mult" if is_cb else "cr_mult", 128)
                luma_mult = p_params.get("cb_luma_mult" if is_cb else "cr_luma_mult", 128)
                offset = p_params.get("cb_offset" if is_cb else "cr_offset", 256)
                if mult == 128 and luma_mult == 192 and offset == 256:
                    label = "Based on luma value"
                else:
                    label = f"{'Cb' if is_cb else 'Cr'} value"

        self.plotter.set_x_label(label)

    def get_p_params(self):
        return self.sidebar.get_p_params()
        
    def get_grain_size(self):
        return self.sidebar.get_grain_size()
        
    def get_seed(self):
        return self.sidebar.get_seed()
        
    def get_event_time_bounds(self):
        return self.sidebar.get_event_time_bounds()


class ARCoefficientsEditor(QDialog):
    def __init__(self, channel: str, editor: SingleEventEditor, parent=None):
        super().__init__(parent)
        self.channel = channel
        self.editor = editor
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setModal(False)
        self.setWindowTitle(f"AR Coefficients - Channel {channel}")
        self.resize(320, 480)
        
        self._updating_table = False
        self.spinboxes = []
        self.current_coeffs = []
        self._undo_stack = deque(maxlen=100)
        self._redo_stack = deque(maxlen=100)
        
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a2e;
                color: #dddddd;
            }
            QTableWidget {
                background-color: #161626;
                color: #dddddd;
                gridline-color: #333355;
                border: 1px solid #333355;
            }
            QHeaderView::section {
                background-color: #252540;
                color: #aaaaaa;
                padding: 4px;
                font-weight: bold;
                border: 1px solid #333355;
            }
            QSpinBox {
                background-color: #1e1e30;
                color: #ffffff;
                border: 1px solid #333355;
                border-radius: 3px;
                padding: 2px;
            }
            QSpinBox:hover, QSpinBox:focus {
                border-color: #4da6ff;
            }
            QPushButton {
                background: #252540;
                color: #4da6ff;
                border: 1px solid #333355;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #3d3d5c;
                color: #ffffff;
            }
            QPushButton:pressed {
                background: #1d1d2c;
            }
            QCheckBox {
                color: #aaaaaa;
                font-weight: bold;
            }
        """)
        
        layout = QVBoxLayout(self)
        
        self.matrix_checkbox = QCheckBox("Show as Matrix")
        self.matrix_checkbox.toggled.connect(self.on_view_mode_changed)
        layout.addWidget(self.matrix_checkbox)
        
        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(2)
        self.table_widget.setHorizontalHeaderLabels(["Coefficient", "Value"])
        self.table_widget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table_widget)
        
        btn_layout = QHBoxLayout()
        
        self.undo_btn = QPushButton("Undo")
        self.undo_btn.clicked.connect(self.undo)
        btn_layout.addWidget(self.undo_btn)
        
        self.redo_btn = QPushButton("Redo")
        self.redo_btn.clicked.connect(self.redo)
        btn_layout.addWidget(self.redo_btn)
        
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self.reset_coefficients)
        btn_layout.addWidget(self.reset_btn)
        
        layout.addLayout(btn_layout)
        
        self.undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self.undo_shortcut.activated.connect(self.undo)
        
        self.redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        self.redo_shortcut.activated.connect(self.redo)
        
        self.refresh_table()

    def on_view_mode_changed(self):
        if self.matrix_checkbox.isChecked():
            if self.width() < 520:
                self.resize(520, self.height())
        self.refresh_table()

    def refresh_table(self):
        self._updating_table = True
        try:
            lag = self.editor.sidebar.get_p_params().get("ar_coeff_lag", 3)
            expected_count = 2 * lag * (lag + 1)
            if self.channel in ("Cb", "Cr"):
                expected_count += 1
                
            is_matrix = self.matrix_checkbox.isChecked()
            
            if is_matrix:
                expected_rows = lag + 1
                if self.channel in ("Cb", "Cr"):
                    expected_rows += 1
                expected_cols = 2 * lag + 1
                if self.channel in ("Cb", "Cr") and expected_cols < 2:
                    expected_cols = 2
            else:
                expected_rows = expected_count
                expected_cols = 2
                
            if len(self.current_coeffs) != expected_count:
                self._undo_stack.clear()
                self._redo_stack.clear()
                
            cy, cb, cr = fgs_parser.extract_ar_coeffs_from_raw_lines(
                self.editor._working.get("raw_lines", [])
            )
            coeffs = cy if self.channel == "Y" else (cb if self.channel == "Cb" else cr)
            
            if len(coeffs) < expected_count:
                coeffs = list(coeffs) + [0] * (expected_count - len(coeffs))
            else:
                coeffs = coeffs[:expected_count]
                
            self.current_coeffs = list(coeffs)
            
            self.table_widget.clearContents()
            self.table_widget.setRowCount(expected_rows)
            self.table_widget.setColumnCount(expected_cols)
            self.table_widget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.spinboxes = []
            
            if not is_matrix:
                self.table_widget.setHorizontalHeaderLabels(["Coefficient", "Value"])
                self.table_widget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
                self.table_widget.verticalHeader().setVisible(False)
                
                for i in range(expected_count):
                    is_cross = (self.channel in ("Cb", "Cr") and i == expected_count - 1)
                    if is_cross:
                        label_text = f"c[{i}] (Cross-Corr)"
                    else:
                        label_text = f"c[{i}]"
                        
                    label_item = QTableWidgetItem(label_text)
                    label_item.setFlags(label_item.flags() & ~Qt.ItemIsEditable)
                    
                    spin = QSpinBox()
                    spin.setRange(-128, 127)
                    spin.setValue(self.current_coeffs[i])
                    spin.valueChanged.connect(self._on_spinbox_changed)
                    self.spinboxes.append(spin)
                    
                    if is_cross:
                        label_item.setFont(QFont("Segoe UI", 9, QFont.Bold))
                        label_item.setForeground(QBrush(QColor("#2ecc71")))
                        label_item.setBackground(QBrush(QColor("#253c3c")))
                        spin.setStyleSheet("QSpinBox { background-color: #253c3c; color: #2ecc71; font-weight: bold; border: 1px solid #2ecc71; }")
                    
                    spin_bg = QTableWidgetItem("")
                    spin_bg.setFlags(spin_bg.flags() & ~Qt.ItemIsEditable)
                    self.table_widget.setItem(i, 0, label_item)
                    self.table_widget.setItem(i, 1, spin_bg)
                    self.table_widget.setCellWidget(i, 1, spin)
            else:
                self.table_widget.verticalHeader().setVisible(True)
                
                headers = [str(col) for col in range(-lag, lag + 1)]
                if lag > 0:
                    headers[lag] = "Center"
                if len(headers) < expected_cols:
                    headers.append("Value")
                self.table_widget.setHorizontalHeaderLabels(headers)
                self.table_widget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
                
                row_labels = [f"y-{lag - i}" for i in range(lag)] + ["y=0"]
                if self.channel in ("Cb", "Cr"):
                    row_labels.append("Cross-Corr")
                self.table_widget.setVerticalHeaderLabels(row_labels)
                
                pos = 0
                for r in range(lag + 1):
                    delta_row = r - lag
                    for c in range(2 * lag + 1):
                        delta_col = c - lag
                        
                        if delta_row == 0 and delta_col == 0:
                            target_item = QTableWidgetItem("Target")
                            target_item.setTextAlignment(Qt.AlignCenter)
                            target_item.setFlags((target_item.flags() & ~Qt.ItemIsEnabled) & ~Qt.ItemIsEditable)
                            target_item.setFont(QFont("Segoe UI", 9, QFont.Bold))
                            target_item.setForeground(QBrush(QColor("#ff4444")))
                            self.table_widget.setItem(r, c, target_item)
                        elif delta_row == 0 and delta_col > 0:
                            empty_item = QTableWidgetItem("-")
                            empty_item.setTextAlignment(Qt.AlignCenter)
                            empty_item.setFlags((empty_item.flags() & ~Qt.ItemIsEnabled) & ~Qt.ItemIsEditable)
                            self.table_widget.setItem(r, c, empty_item)
                        else:
                            spin = QSpinBox()
                            spin.setRange(-128, 127)
                            spin.setValue(self.current_coeffs[pos])
                            spin.valueChanged.connect(self._on_spinbox_changed)
                            self.spinboxes.append(spin)
                            spin_bg = QTableWidgetItem("")
                            spin_bg.setFlags(spin_bg.flags() & ~Qt.ItemIsEditable)
                            self.table_widget.setItem(r, c, spin_bg)
                            self.table_widget.setCellWidget(r, c, spin)
                            pos += 1
                            
                if self.channel in ("Cb", "Cr"):
                    cross_row = lag + 1
                    label_item = QTableWidgetItem("Cross-Correlation")
                    label_item.setFlags(label_item.flags() & ~Qt.ItemIsEditable)
                    label_item.setFont(QFont("Segoe UI", 9, QFont.Bold))
                    label_item.setForeground(QBrush(QColor("#2ecc71")))
                    label_item.setBackground(QBrush(QColor("#253c3c")))
                    self.table_widget.setItem(cross_row, 0, label_item)
                    
                    spin = QSpinBox()
                    spin.setRange(-128, 127)
                    spin.setValue(self.current_coeffs[pos])
                    spin.valueChanged.connect(self._on_spinbox_changed)
                    spin.setStyleSheet("QSpinBox { background-color: #253c3c; color: #2ecc71; font-weight: bold; border: 1px solid #2ecc71; }")
                    self.spinboxes.append(spin)
                    spin_bg = QTableWidgetItem("")
                    spin_bg.setFlags(spin_bg.flags() & ~Qt.ItemIsEditable)
                    self.table_widget.setItem(cross_row, 1, spin_bg)
                    self.table_widget.setCellWidget(cross_row, 1, spin)
                    pos += 1
                    
                    for c in range(2, expected_cols):
                        empty_item = QTableWidgetItem("-")
                        empty_item.setTextAlignment(Qt.AlignCenter)
                        empty_item.setFlags((empty_item.flags() & ~Qt.ItemIsEnabled) & ~Qt.ItemIsEditable)
                        empty_item.setBackground(QBrush(QColor("#1e2d2d")))
                        self.table_widget.setItem(cross_row, c, empty_item)
        finally:
            self._updating_table = False

    def get_current_values(self) -> list[int]:
        return [sb.value() for sb in self.spinboxes]

    def _on_spinbox_changed(self):
        if self._updating_table:
            return
            
        self._undo_stack.append(list(self.current_coeffs))
        self._redo_stack.clear()
        
        self.current_coeffs = self.get_current_values()
        self.editor.update_ar_coeffs(self.channel, self.current_coeffs)

    def _apply_coefficients(self, coeffs: list[int]):
        self._updating_table = True
        try:
            for sb, val in zip(self.spinboxes, coeffs):
                sb.setValue(val)
            self.current_coeffs = list(coeffs)
        finally:
            self._updating_table = False
            
        self.editor.update_ar_coeffs(self.channel, self.current_coeffs)

    def undo(self):
        if not self._undo_stack:
            return
        current = self.get_current_values()
        self._redo_stack.append(current)
        
        previous = self._undo_stack.pop()
        self._apply_coefficients(previous)

    def redo(self):
        if not self._redo_stack:
            return
        current = self.get_current_values()
        self._undo_stack.append(current)
        
        next_state = self._redo_stack.pop()
        self._apply_coefficients(next_state)

    def reset_coefficients(self):
        orig = self.editor.original_ar_coeffs.get(self.channel, [])
        lag = self.editor.sidebar.get_p_params().get("ar_coeff_lag", 3)
        expected_count = 2 * lag * (lag + 1)
        if self.channel in ("Cb", "Cr"):
            expected_count += 1
            
        new_coeffs = list(orig)
        if len(new_coeffs) < expected_count:
            new_coeffs.extend([0] * (expected_count - len(new_coeffs)))
        else:
            new_coeffs = new_coeffs[:expected_count]
            
        current = self.get_current_values()
        if new_coeffs != current:
            self._undo_stack.append(current)
            self._redo_stack.clear()
            self._apply_coefficients(new_coeffs)

    def closeEvent(self, event):
        if self.editor and self.channel in self.editor._ar_windows:
            self.editor._ar_windows[self.channel] = None
        super().closeEvent(event)

    def reject(self):
        if self.editor and self.channel in self.editor._ar_windows:
            self.editor._ar_windows[self.channel] = None
        super().reject()
