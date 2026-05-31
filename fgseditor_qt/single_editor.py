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
)
from PySide6.QtCore import Qt, Signal

from . import fgs_parser
from . import fgs_math
from .time_utils import ticks_to_seconds, ticks_to_frames, ticks_to_timecode

from .plotter import InteractiveFGSPlotter
from .grain_preview import GrainPreviewPlotter
from .params_sidebar import ParamsSidebar
from .panels.tabs_widget import SettingsTabsBar


class SingleEventEditor(QWidget):
    # Signals for dynamic FGS mode
    save_event_requested = Signal()
    cancel_requested = Signal()

    # Signals for static FGS mode
    close_fgs_requested = Signal()
    save_fgs_requested = Signal()
    save_bin_requested = Signal()
    save_apply_requested = Signal()
    save_plot_requested = Signal()
    
    # Generic signals
    state_changed = Signal(bool) # Emits True if dirty, False if not

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

        from .settings_manager import get_setting
        undo_size = get_setting("undo_stack_size", 100)
        self._undo_stack = deque(maxlen=undo_size)
        self._redo_stack = deque(maxlen=undo_size)
        self._last_known_state = None
        
        # References for dynamic timeline info (FPS)
        self.fps_callback = None

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Top frame for static (Close FGS, file label)
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

        # Middle controls bar (Common + Specific)
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

        mid_layout.addStretch(1)
        
        self.time_info_label = QLabel()
        self.time_info_label.setStyleSheet(
            "color: #4da6ff; font-size: 12px; font-family: monospace;"
        )
        self.time_info_label.setToolTip(
            "Event time range in seconds and corresponding frame numbers at the selected FPS"
        )
        mid_layout.addWidget(self.time_info_label, stretch=0)
        if not self.is_dynamic:
            self.time_info_label.hide()

        self.validation_warning_label = QLabel()
        self.validation_warning_label.setStyleSheet(
            "color: #ff4444; font-weight: bold; background: #220000; padding: 2px 6px; border-radius: 4px;"
        )
        self.validation_warning_label.hide()
        mid_layout.addWidget(self.validation_warning_label)

        # Dynamic specific buttons
        self.save_event_btn = QPushButton("Save Event")
        self.save_event_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.save_event_btn.clicked.connect(self.save_event_requested.emit)
        self.save_event_btn.setEnabled(False)
        mid_layout.addWidget(self.save_event_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        mid_layout.addWidget(self.cancel_btn)

        # Static specific buttons
        self.save_fgs_btn = QPushButton("Save FGS")
        self.save_fgs_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.save_fgs_btn.clicked.connect(self.save_fgs_requested.emit)
        self.save_fgs_btn.setEnabled(False)
        mid_layout.addWidget(self.save_fgs_btn)

        self.save_bin_btn = QPushButton("Save AFGS1 Bin")
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

        # Toggle visibility based on mode
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

        # Global shortcuts (only added if not already handled by parent window to avoid conflicts)
        # Often these are better handled by the main window or dialog itself.
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

    def load_event(self, event_dict, event_idx=-1):
        self.event_dict = event_dict
        self.event_idx = event_idx
        self._working = copy.deepcopy(event_dict) if event_dict else {}

        self.original_scale_data = copy.deepcopy(
            self._working.get("scale_data") or fgs_parser.get_scale_data(self._working)
        )
        self.current_scale_data = copy.deepcopy(self.original_scale_data)
        
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

        self.reset_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)

        self._refresh_time_info()
        self._refresh_grain_preview()
        self._update_ui_state()
        self._update_last_known_state()

    def set_time_limits(self, min_t, max_t):
        self.sidebar.set_time_limits(min_t, max_t)

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
        if self.plotter:
            self.plotter.close_plot()

    def get_working_event(self):
        # Update working dict with current state
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
            
            # Reset originals
            self.original_scale_data = copy.deepcopy(self.current_scale_data)
            self.original_p_params = self.sidebar.get_p_params()
            self.original_grain_size = self.sidebar.get_grain_size()
            self.original_time_bounds = self.sidebar.get_event_time_bounds()
            self._update_ui_state()

    # --- UI Logic Methods ---

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

    def on_channel_change(self, text):
        self.plotter.set_active_channel(text)
        self._update_plot_x_label()

    def on_plotter_changed(self):
        self.current_scale_data = copy.deepcopy(self.plotter.current_data)
        self._sync_chromas_if_needed()
        self._refresh_grain_preview()
        self._update_ui_state()
        self._update_last_known_state()

    def _sync_chromas_if_needed(self):
        p_params = self.sidebar.get_p_params()
        linked = bool(p_params.get("chroma_scaling_from_luma", 0))

        self.plotter.set_chroma_linked(linked)

        if linked:
            # Sync sCb and sCr with sY
            sy = self.current_scale_data.get("sY", {"x": [], "y": []})
            self.current_scale_data["sCb"] = copy.deepcopy(sy)
            self.current_scale_data["sCr"] = copy.deepcopy(sy)

            self.plotter.current_data = copy.deepcopy(self.current_scale_data)
            self.plotter.refresh()

    def _on_params_changed(self, p_params: dict):
        self._push_undo_global()
        self._working["p_params"] = p_params
        
        self._sync_chromas_if_needed()
            
        self._refresh_grain_preview(p_params=p_params)
        self._update_ui_state()
        self._update_last_known_state()

    def _on_grain_size_changed(self, size: str):
        self._push_undo_global()
        from .fgs_size_table import apply_grain_preset_to_event
        apply_grain_preset_to_event(self._working, size)
        self.sidebar.load_from_event(self._working, size_id=size)

        updated_scale_data = self._working.get(
            "scale_data",
            {"sY": {"x": [], "y": []}, "sCb": {"x": [], "y": []}, "sCr": {"x": [], "y": []}},
        )
        self.current_scale_data = copy.deepcopy(updated_scale_data)
        self.plotter.set_data(self.current_scale_data)

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
            c_prefixes = ["cY", "cCb", "cCr"]
            tmpl_lines_map = {}
            for line in template_evt.get("raw_lines", []):
                tokens = line.strip().split()
                if tokens and tokens[0] in c_prefixes:
                    tmpl_lines_map[tokens[0]] = line

            for line in self._working.get("raw_lines", []):
                tokens = line.strip().split()
                if tokens and tokens[0] in c_prefixes:
                    if tokens[0] in tmpl_lines_map:
                        new_lines.append(tmpl_lines_map[tokens[0]])
                        del tmpl_lines_map[tokens[0]]
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)

            for k, val in tmpl_lines_map.items():
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

    def undo(self):
        if not self._undo_stack or not self._last_known_state:
            return
        self._redo_stack.append(copy.deepcopy(self._last_known_state))

        state = self._undo_stack.pop()
        self.current_scale_data = copy.deepcopy(state["data"])
        self._working = copy.deepcopy(state.get("working", self._working))
        self.sidebar.set_full_state(state["sidebar"])

        self.plotter.current_data = copy.deepcopy(self.current_scale_data)
        self.plotter.refresh()
        self._refresh_grain_preview()
        self._refresh_time_info()
        self._update_ui_state()
        self._update_last_known_state()

    def redo(self):
        if not self._redo_stack or not self._last_known_state:
            return
        self._undo_stack.append(copy.deepcopy(self._last_known_state))

        state = self._redo_stack.pop()
        self.current_scale_data = copy.deepcopy(state["data"])
        self._working = copy.deepcopy(state.get("working", self._working))
        self.sidebar.set_full_state(state["sidebar"])

        self.plotter.current_data = copy.deepcopy(self.current_scale_data)
        self.plotter.refresh()
        self._refresh_grain_preview()
        self._refresh_time_info()
        self._update_ui_state()
        self._update_last_known_state()

    def reset_data(self):
        if not self.original_scale_data:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Reset",
            "Are you sure you want to revert all changes?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._push_undo_global()
            self.current_scale_data = copy.deepcopy(self.original_scale_data)
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
        dialog.setFixedWidth(260)
        dialog.setStyleSheet("background-color: #1a1a2e; color: #dddddd;")

        vbox = QVBoxLayout(dialog)
        vbox.setContentsMargins(15, 15, 15, 15)
        vbox.setSpacing(12)

        lbl = QLabel("Select channels to clear:")
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
            "QPushButton { background: #5c1a1a; color: #ff6b6b; border: 1px solid #ff4444; border-radius: 4px; padding: 6px; font-weight: bold; }"
            "QPushButton:hover { background: #7c2a2a; }"
        )

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            "QPushButton { background: #2d2d2d; color: #aaaaaa; border: 1px solid #444; border-radius: 4px; padding: 6px; }"
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
        if self.current_scale_data != self.original_scale_data:
            return True
        if self.sidebar.get_p_params() != self.original_p_params:
            return True
        if self.sidebar.get_grain_size() != self.original_grain_size:
            return True
        if self.sidebar.get_event_time_bounds() != self.original_time_bounds:
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

            # Point count check
            max_pts = 14 if ch == "Y" else 10
            if len(xs) > max_pts:
                all_errors.append(f"Channel {ch}: Too many scaling points ({len(xs)} > {max_pts}).")

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
        self.save_fgs_btn.setEnabled(dirty)
        
        self.state_changed.emit(dirty)

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
