import copy
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
from .time_utils import ticks_to_seconds, ticks_to_frames, ticks_to_timecode

from .plotter import InteractiveFGSPlotter
from .grain_preview import GrainPreviewPlotter
from .params_sidebar import ParamsSidebar
from .shortcuts import create_standard_menu


class EventEditorUI(QDialog):
    def __init__(self, dynamic_timeline_ui, event_data):
        super().__init__()
        self.dynamic_timeline_ui = dynamic_timeline_ui
        self.event_data = event_data
        self.event_dict = event_data["event"]
        self.event_idx = event_data["event_idx"]

        self.setWindowTitle(f"Edit FGS Event {self.event_idx + 1}")
        self.setMinimumSize(1000, 650)
        self.setAttribute(Qt.WA_DeleteOnClose)

        self.original_scale_data = copy.deepcopy(self.event_dict["scale_data"])
        self.current_scale_data = copy.deepcopy(self.event_dict["scale_data"])
        self.original_p_params = {}
        self.original_grain_size = 0

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

        # Horizontal split: sidebar | right area
        h_splitter = QSplitter(Qt.Horizontal)
        h_splitter.setHandleWidth(4)
        h_splitter.setStyleSheet("QSplitter::handle { background: #333355; }")
        layout.addWidget(h_splitter, stretch=1)

        # Sidebar
        self.sidebar = ParamsSidebar()
        self.sidebar.params_changed.connect(self._on_params_changed)
        self.sidebar.grain_size_changed.connect(self._on_grain_size_changed)
        # Populate from this event's p_params
        self.sidebar.load_from_event(self.event_dict, size_id=-1)
        h_splitter.addWidget(self.sidebar)

        # Right: vertical splitter (main plot | grain preview)
        v_splitter = QSplitter(Qt.Vertical)
        v_splitter.setHandleWidth(4)
        v_splitter.setStyleSheet("QSplitter::handle { background: #333355; }")
        h_splitter.addWidget(v_splitter)

        self.plotter = InteractiveFGSPlotter()
        self.plotter.data_changed.connect(self.on_plotter_changed)
        v_splitter.addWidget(self.plotter)

        self.grain_preview = GrainPreviewPlotter()
        self.grain_preview.setMinimumHeight(130)
        v_splitter.addWidget(self.grain_preview)

        v_splitter.setSizes([420, 220])
        h_splitter.setSizes([200, 800])

        self.plotter.set_data(self.current_scale_data)

        # Capture originals after first load
        self.original_p_params = self.sidebar.get_p_params()
        self.original_grain_size = self.sidebar.get_grain_size()

        self._refresh_grain_preview()
        self._update_ui_state()

    def _refresh_time_info(self):
        start_ticks = self.event_dict.get("start_time", 0)
        end_ticks = self.event_dict.get("end_time", 0)
        start_s = ticks_to_seconds(start_ticks)
        end_s = ticks_to_seconds(end_ticks)
        start_tc = ticks_to_timecode(start_ticks)
        end_tc = ticks_to_timecode(end_ticks)

        # Try to get FPS from the parent timeline
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
        self.plotter.set_active_channel(text)

    def on_plotter_changed(self):
        self.current_scale_data = copy.deepcopy(self.plotter.current_data)
        self._refresh_grain_preview()
        self._update_ui_state()

    def _on_params_changed(self, p_params: dict):
        self.event_dict["p_params"] = p_params
        self._refresh_grain_preview(p_params=p_params)
        self._update_ui_state()

    def _on_grain_size_changed(self, size: int):
        from .fgs_size_table import apply_size_preset_to_event

        apply_size_preset_to_event(self.event_dict, size)
        # Sync sidebar UI with the new p_params from the preset, keeping the selected size_id
        self.sidebar.load_from_event(self.event_dict, size_id=size)
        self._refresh_grain_preview(grain_size=size)
        self._update_ui_state()

    def is_dirty(self) -> bool:
        """Check if any data or parameters have changed from the original markers."""
        if self.current_scale_data != self.original_scale_data:
            return True
        if self.sidebar.get_p_params() != self.original_p_params:
            return True
        if self.sidebar.get_grain_size() != self.original_grain_size:
            return True
        return False

    def _get_validation_errors(self) -> list[str]:
        p_params = self.sidebar.get_p_params()
        grain_size = self.sidebar.get_grain_size()
        ar_shift = p_params.get("ar_coeff_shift", 8)
        autobalance = self.sidebar.get_autobalance()

        from .fgs_math import (
            extract_ar_coeffs_from_raw_lines,
            compute_export_scale_factor,
            validate_fgs_pipeline,
        )

        cy_coeffs, cb_coeffs, cr_coeffs = extract_ar_coeffs_from_raw_lines(
            self.event_dict.get("raw_lines", [])
        )

        all_errors = []
        for ch, coeffs, ch_key in [
            ("Y", cy_coeffs, "sY"),
            ("Cb", cb_coeffs, "sCb"),
            ("Cr", cr_coeffs, "sCr"),
        ]:
            ys = self.current_scale_data.get(ch_key, {}).get("y", [])
            export_scale = (
                compute_export_scale_factor(grain_size, coeffs, ar_shift)
                if autobalance
                else 1.0
            )

            errors = validate_fgs_pipeline(coeffs, ar_shift, ys, export_scale)
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
        noise_setting = self.sidebar.get_noise_setting()
        autobalance = self.sidebar.get_autobalance()

        from .fgs_math import extract_ar_coeffs_from_raw_lines

        cy_coeffs, cb_coeffs, cr_coeffs = extract_ar_coeffs_from_raw_lines(
            self.event_dict.get("raw_lines", [])
        )
        self.grain_preview.update_preview(
            self.current_scale_data,
            p_params=p_params,
            grain_size=grain_size,
            cy_coeffs=cy_coeffs,
            cb_coeffs=cb_coeffs,
            cr_coeffs=cr_coeffs,
            noise_setting=noise_setting,
            autobalance=autobalance,
        )
        self.sidebar.set_ar_shift_warning(self.grain_preview.is_ar_unstable())

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
                # self.save_event() calls self.accept(), which closes the dialog
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

        self.dynamic_timeline_ui._push_undo()
        self.event_dict["scale_data"] = copy.deepcopy(self.current_scale_data)

        # Persist sidebar parameters back into the event so dynamic save picks them up
        self.event_dict["p_params"] = self.sidebar.get_p_params()
        self.event_dict["grain_size"] = self.sidebar.get_grain_size()

        from .fgs_parser import avg_sy_strength

        new_strength = avg_sy_strength(self.event_dict)

        # Reset originals
        self.original_scale_data = copy.deepcopy(self.current_scale_data)
        self.original_p_params = self.sidebar.get_p_params()
        self.original_grain_size = self.sidebar.get_grain_size()
        self._update_ui_state()

        QMessageBox.information(
            self,
            "Event Updated",
            f"Event {self.event_idx + 1} updated.\nNew avg sY strength: {new_strength:.2f}",
        )

        self.dynamic_timeline_ui.build_timeline()
        self.accept()
