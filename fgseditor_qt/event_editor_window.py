import copy
from collections import deque
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QComboBox,
    QMessageBox,
    QFrame,
    QSizePolicy,
    QSplitter,
)
from PySide6.QtCore import Qt
from . import fgs_parser
from . import fgs_math
from .time_utils import ticks_to_seconds, ticks_to_frames, ticks_to_timecode

from .plotter import InteractiveFGSPlotter
from .grain_preview import GrainPreviewPlotter
from .params_sidebar import ParamsSidebar
from .shortcuts import create_standard_menu
from .panels.tabs_widget import SettingsTabsBar


class EventEditorUI(QDialog):
    def __init__(self, dynamic_timeline_ui, event_data):
        super().__init__()
        try:
            self.setWindowFlag(Qt.Window, True)
            self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
            self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
            self.setWindowFlag(Qt.WindowCloseButtonHint, True)
            self.setWindowFlag(Qt.WindowSystemMenuHint, True)
        except Exception:
            pass
        self.dynamic_timeline_ui = dynamic_timeline_ui
        self.event_data = event_data
        self.event_dict = event_data["event"]
        self.event_idx = event_data["event_idx"]

        self._working = copy.deepcopy(self.event_dict)

        self.setWindowTitle(f"Edit FGS Event {self.event_idx + 1}")
        self.setMinimumSize(1100, 720)
        self.resize(1100, 720)
        self.setAttribute(Qt.WA_DeleteOnClose)

        self.original_scale_data = copy.deepcopy(
            self._working.get("scale_data") or fgs_parser.get_scale_data(self._working)
        )
        self.current_scale_data = copy.deepcopy(
            self._working.get("scale_data") or fgs_parser.get_scale_data(self._working)
        )
        self.original_p_params = {}
        self.original_grain_size = "-1"
        self.original_time_bounds = (0, 0)

        self._undo_stack = deque(maxlen=100)
        self._redo_stack = deque(maxlen=100)
        self._last_known_state = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        menu_bar = create_standard_menu(self)
        layout.setMenuBar(menu_bar)

        # Top toolbar
        top_frame = QFrame()
        top_frame.setObjectName("toolbar")
        controls_layout = QHBoxLayout(top_frame)
        controls_layout.setContentsMargins(10, 6, 10, 6)

        controls_layout.addWidget(QLabel("Channel:"), stretch=0)

        self.channel_dropdown = QComboBox()
        self.channel_dropdown.addItems(["sY", "sCb", "sCr"])
        self.channel_dropdown.currentTextChanged.connect(self.on_channel_change)
        self.channel_dropdown.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        controls_layout.addWidget(self.channel_dropdown, stretch=0)

        controls_layout.addStretch()

        self.time_info_label = QLabel()
        self.time_info_label.setStyleSheet(
            "color: #4da6ff; font-size: 12px; font-family: monospace;"
        )
        self.time_info_label.setToolTip(
            "Event time range in seconds and corresponding frame numbers at the selected FPS"
        )
        controls_layout.addWidget(self.time_info_label, stretch=0)
        self._refresh_time_info()

        controls_layout.addSpacing(12)

        self.validation_warning_label = QLabel()
        self.validation_warning_label.setStyleSheet(
            "color: #ff4444; font-weight: bold; background: #220000; padding: 2px 6px; border-radius: 4px;"
        )
        self.validation_warning_label.hide()
        controls_layout.addWidget(self.validation_warning_label, stretch=0)

        self.save_btn = QPushButton("Save Event")
        self.save_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.save_btn.clicked.connect(self.save_event)
        controls_layout.addWidget(self.save_btn, stretch=0)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.cancel_btn.clicked.connect(self.close)
        controls_layout.addWidget(self.cancel_btn, stretch=0)

        layout.addWidget(top_frame)

        self.tabs_bar = SettingsTabsBar()
        layout.addWidget(self.tabs_bar)

        # Horizontal split: sidebar | right area
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

        # Apply limits from neighbors
        all_events = self.dynamic_timeline_ui.events
        min_t = 0
        max_t = 2**63 - 1
        if self.event_idx > 0:
            min_t = all_events[self.event_idx - 1]["end_time"]
        if self.event_idx < len(all_events) - 1:
            max_t = all_events[self.event_idx + 1]["start_time"]

        self.sidebar.set_time_limits(min_t, max_t)
        self.sidebar.load_from_event(self._working, size_id="-1")
        h_splitter.addWidget(self.sidebar)

        # Right: vertical splitter (main plot | grain preview)
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

        # Global shortcuts
        from PySide6.QtGui import QShortcut, QKeySequence

        self.undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self.undo_shortcut.activated.connect(self.undo)
        self.redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        self.redo_shortcut.activated.connect(self.redo)

        self.grain_preview = GrainPreviewPlotter()
        self.grain_preview.setMinimumHeight(130)
        v_splitter.addWidget(self.grain_preview)

        v_splitter.setSizes([420, 220])
        h_splitter.setSizes([200, 800])

        self.plotter.set_data(self.current_scale_data)

        # Capture originals after first load
        self.original_p_params = self.sidebar.get_p_params()
        self.original_grain_size = self.sidebar.get_grain_size()
        self.original_time_bounds = self.sidebar.get_event_time_bounds()

        self._refresh_grain_preview()
        self._update_ui_state()
        self._update_last_known_state()

    def _refresh_time_info(self):
        start_ticks = self.event_dict.get("start_time", 0)
        end_ticks = self.event_dict.get("end_time", 0)
        start_s = ticks_to_seconds(start_ticks)
        end_s = ticks_to_seconds(end_ticks)
        start_tc = ticks_to_timecode(start_ticks)
        end_tc = ticks_to_timecode(end_ticks)

        fps = None
        try:
            fps = self.dynamic_timeline_ui._current_fps()
        except Exception:
            pass

        if fps:
            start_f = ticks_to_frames(start_ticks, fps)
            end_f = ticks_to_frames(end_ticks, fps)
            fps_label = self.dynamic_timeline_ui.fps_combo.currentText()
            self.time_info_label.setText(
                f"⏱ {start_tc}  ({start_s:.4f}s)  →  {end_tc}  ({end_s:.4f}s)"
                f"   │   🎞 frame {start_f} → {end_f}  @ {fps_label} fps"
            )
        else:
            self.time_info_label.setText(
                f"⏱ {start_tc}  ({start_s:.4f}s)  →  {end_tc}  ({end_s:.4f}s)"
            )

    def on_channel_change(self, text):
        self.plotter.active_channel = text
        self._update_plot_x_label()
        self.plotter.refresh()

    def on_plotter_changed(self):
        self.current_scale_data = copy.deepcopy(self.plotter.current_data)
        self._refresh_grain_preview()
        self._update_ui_state()
        self._update_last_known_state()

    def _on_params_changed(self, p_params: dict):
        self._push_undo_global()
        # Update working copy only
        self._working["p_params"] = p_params
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
            {
                "sY": {"x": [], "y": []},
                "sCb": {"x": [], "y": []},
                "sCr": {"x": [], "y": []},
            },
        )
        self.current_scale_data = copy.deepcopy(updated_scale_data)
        self.plotter.set_data(self.current_scale_data)

        self._refresh_grain_preview(grain_size=size)
        self._update_ui_state()
        self._update_last_known_state()

    def _on_photon_noise_changed(self, payload: dict):
        if not self.current_scale_data:
            return

        if (
            self.current_scale_data["sY"]["x"] == payload["sY"]["x"]
            and self.current_scale_data["sY"]["y"] == payload["sY"]["y"]
        ):
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
        import copy

        if mode in (0, 1):
            if "scale_data" in template_evt and template_evt["scale_data"]:
                for ch in ["sY", "sCb", "sCr"]:
                    if ch in template_evt["scale_data"]:
                        self.current_scale_data[ch] = copy.deepcopy(
                            template_evt["scale_data"][ch]
                        )

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

        if mode == 0:
            if template_evt.get("p_params"):
                self._working["p_params"] = copy.deepcopy(template_evt["p_params"])

        # Reload sidebar UI entirely
        self.sidebar.load_from_event(self._working, size_id="-1")
        self.plotter.current_data = copy.deepcopy(self.current_scale_data)
        self.plotter.refresh()
        self._refresh_grain_preview()
        self._update_ui_state()
        self._update_last_known_state()
        self._update_ui_state()

    def _on_time_changed(self, start: int, end: int):
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
        self._update_ui_state()
        self._update_last_known_state()

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

    def _get_validation_errors(self) -> list[str]:
        p_params = self.sidebar.get_p_params()
        ar_shift = p_params.get("ar_coeff_shift", 8)

        cy_coeffs, cb_coeffs, cr_coeffs = fgs_parser.extract_ar_coeffs_from_raw_lines(
            self._working.get("raw_lines", [])
        )

        all_errors = []
        for ch, coeffs, ch_key in [
            ("Y", cy_coeffs, "sY"),
            ("Cb", cb_coeffs, "sCb"),
            ("Cr", cr_coeffs, "sCr"),
        ]:
            ys = self.current_scale_data.get(ch_key, {}).get("y", [])

            errors = fgs_math.validate_fgs_pipeline(coeffs, ar_shift, ys)
            if errors:
                all_errors.append(
                    f"Channel {ch}:\n" + "\n".join(" - " + e for e in errors)
                )

        return all_errors

    def _update_ui_state(self):
        dirty = self.is_dirty()

        errors = self._get_validation_errors()
        if errors:
            self.validation_warning_label.setText("⚠ UNSAFE PRESET")
            self.validation_warning_label.setToolTip("\n\n".join(errors))
            self.validation_warning_label.show()
        else:
            self.validation_warning_label.hide()

        self.save_btn.setEnabled(dirty)

        event_id = self.event_dict.get("event_id", f"Idx {self.event_idx}")
        title = f"Event Editor - {event_id}"
        if dirty:
            title += " *"
        self.setWindowTitle(title)

    def _refresh_grain_preview(self, p_params=None, grain_size=None):
        if p_params is None:
            p_params = self.sidebar.get_p_params()
        if grain_size is None:
            grain_size = self.sidebar.get_grain_size()

        seed = self.sidebar.get_seed()

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
                is_cb = (channel == "sCb")
                mult = p_params.get("cb_mult" if is_cb else "cr_mult", 128)
                luma_mult = p_params.get("cb_luma_mult" if is_cb else "cr_luma_mult", 128)
                offset = p_params.get("cb_offset" if is_cb else "cr_offset", 256)
                if mult == 128 and luma_mult == 192 and offset == 256:
                    label = "Based on luma value"
                else:
                    label = f"{'Cb' if is_cb else 'Cr'} value"
        
        self.plotter.set_x_label(label)

    def closeEvent(self, event):
        if self.is_dirty():
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes in this event. Save them before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Save:
                self.save_event()
            elif reply == QMessageBox.Discard:
                if self.plotter:
                    self.plotter.close_plot()
                    self.plotter = None
                event.accept()
            else:
                event.ignore()
        else:
            if self.plotter:
                self.plotter.close_plot()
                self.plotter = None
            super().closeEvent(event)

    def save_event(self):
        errors = self._get_validation_errors()
        if errors:
            error_text = "\n".join(errors)
            reply = QMessageBox.warning(
                self,
                "Unsafe Preset",
                f"The current preset has stability or clipping issues:\n\n{error_text}\n\nAre you sure you want to save anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return

        self._working["scale_data"] = copy.deepcopy(self.current_scale_data)
        self._working["p_params"] = self.sidebar.get_p_params()
        self._working["grain_size"] = self.sidebar.get_grain_size()
        st, et = self.sidebar.get_event_time_bounds()
        self._working["start_time"] = st
        self._working["end_time"] = et

        self.event_dict.update(self._working)

        self.dynamic_timeline_ui._push_undo()
        self.dynamic_timeline_ui.build_timeline()

        from .dynamic_ui import _process_timeline_event
        
        _, _, new_strength = _process_timeline_event((0, "", self.event_dict))

        self.original_scale_data = copy.deepcopy(self.current_scale_data)
        self.original_p_params = self.sidebar.get_p_params()
        self.original_grain_size = self.sidebar.get_grain_size()
        self.original_time_bounds = self.sidebar.get_event_time_bounds()
        self._update_ui_state()

        QMessageBox.information(
            self,
            "Event Updated",
            f"Event {self.event_idx + 1} updated.\nNew effective amplitude: {new_strength:.2f}",
        )

        self.dynamic_timeline_ui.build_timeline()
        self.dynamic_timeline_ui._update_ui_state()
        self.accept()
