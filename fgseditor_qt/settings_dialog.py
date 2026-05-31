from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QMessageBox,
    QTabWidget,
    QWidget,
    QSpinBox,
    QDoubleSpinBox,
    QColorDialog,
    QFrame,
    QApplication,
)
from PySide6.QtCore import QProcess
from PySide6.QtGui import QColor
import os
import sys
from .settings_manager import get_setting, set_setting


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        self.setModal(True)

        main_layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # --- GENERAL TAB ---
        self.tab_general = QWidget()
        gen_layout = QVBoxLayout(self.tab_general)
        gen_layout.setSpacing(15)

        exec_group = QGroupBox("Executables Paths")
        exec_layout = QVBoxLayout(exec_group)

        g_layout = QHBoxLayout()
        g_layout.addWidget(QLabel("grav1synth:"))
        self.grav1synth_input = QLineEdit(get_setting("grav1synth_path", ""))
        self.grav1synth_input.setPlaceholderText(
            "Leave empty to use system PATH or next to app"
        )
        g_layout.addWidget(self.grav1synth_input)
        g_btn = QPushButton("Browse")
        g_btn.clicked.connect(
            lambda: self._browse_exe(self.grav1synth_input, "grav1synth")
        )
        g_layout.addWidget(g_btn)
        exec_layout.addLayout(g_layout)

        ff_layout = QHBoxLayout()
        ff_layout.addWidget(QLabel("ffmpeg:    "))
        self.ffmpeg_input = QLineEdit(get_setting("ffmpeg_path", ""))
        self.ffmpeg_input.setPlaceholderText(
            "Leave empty to use system PATH or next to app"
        )
        ff_layout.addWidget(self.ffmpeg_input)
        ff_btn = QPushButton("Browse")
        ff_btn.clicked.connect(lambda: self._browse_exe(self.ffmpeg_input, "ffmpeg"))
        ff_layout.addWidget(ff_btn)
        exec_layout.addLayout(ff_layout)

        fp_layout = QHBoxLayout()
        fp_layout.addWidget(QLabel("ffprobe:   "))
        self.ffprobe_input = QLineEdit(get_setting("ffprobe_path", ""))
        self.ffprobe_input.setPlaceholderText(
            "Leave empty to use system PATH or next to app"
        )
        fp_layout.addWidget(self.ffprobe_input)
        fp_btn = QPushButton("Browse")
        fp_btn.clicked.connect(lambda: self._browse_exe(self.ffprobe_input, "ffprobe"))
        fp_layout.addWidget(fp_btn)
        exec_layout.addLayout(fp_layout)

        gen_layout.addWidget(exec_group)

        time_group = QGroupBox("Timeline Defaults")
        time_layout = QVBoxLayout(time_group)

        fps_h = QHBoxLayout()
        fps_h.addWidget(QLabel("Default FPS:"))
        self.fps_combo = QComboBox()
        self.fps_combo.addItems(
            ["23.976", "24", "25", "29.97", "30", "50", "59.94", "60"]
        )
        self.fps_combo.setCurrentText(get_setting("default_fps", "24"))
        fps_h.addWidget(self.fps_combo)
        fps_h.addStretch()
        time_layout.addLayout(fps_h)

        fmt_h = QHBoxLayout()
        fmt_h.addWidget(QLabel("Default Time Format:"))
        self.time_combo = QComboBox()
        self.time_combo.addItems(["Frames", "Seconds", "Timestamp"])
        self.time_combo.setCurrentText(get_setting("default_time_format", "Frames"))
        fmt_h.addWidget(self.time_combo)
        fmt_h.addStretch()
        time_layout.addLayout(fmt_h)

        gen_layout.addWidget(time_group)

        warn_group = QGroupBox("Advanced")
        warn_layout = QVBoxLayout(warn_group)
        self.warnings_check = QCheckBox(
            "Show blocking popups for unsafe FGS configurations"
        )
        self.warnings_check.setChecked(get_setting("show_unsafe_warnings", True))
        warn_layout.addWidget(self.warnings_check)
        gen_layout.addWidget(warn_group)

        gen_layout.addStretch()
        self.tabs.addTab(self.tab_general, "General")

        # --- EXPORT & AUTOSAVE TAB ---
        self.tab_export = QWidget()
        exp_layout = QVBoxLayout(self.tab_export)
        exp_layout.setSpacing(15)

        auto_group = QGroupBox("Autosave")
        auto_layout = QHBoxLayout(auto_group)
        auto_layout.addWidget(QLabel("Autosave Interval (minutes):"))
        self.autosave_spin = QSpinBox()
        self.autosave_spin.setRange(0, 1440)
        self.autosave_spin.setValue(get_setting("autosave_interval_minutes", 5))
        self.autosave_spin.setToolTip(
            "Set to 0 to disable autosave. Minimum interval is 1 minute."
        )
        auto_layout.addWidget(self.autosave_spin)
        auto_layout.addStretch()
        exp_layout.addWidget(auto_group)

        fall_group = QGroupBox("Binary Export")
        fall_layout = QHBoxLayout(fall_group)
        fall_layout.addWidget(QLabel("Fallback Export Duration (Frames):"))
        self.fallback_spin = QSpinBox()
        self.fallback_spin.setRange(1, 10000000)
        self.fallback_spin.setValue(get_setting("fallback_export_frames", 150000))
        self.fallback_spin.setToolTip(
            "Used when exporting a binary payload without a video loaded."
        )
        fall_layout.addWidget(self.fallback_spin)
        fall_layout.addStretch()
        exp_layout.addWidget(fall_group)

        exp_layout.addStretch()
        self.tabs.addTab(self.tab_export, "Export")

        # --- PLOTTER TAB ---
        self.tab_plotter = QWidget()
        plot_layout = QVBoxLayout(self.tab_plotter)
        plot_layout.setSpacing(15)

        zoom_group = QGroupBox("Interaction")
        zoom_layout = QHBoxLayout(zoom_group)
        zoom_layout.addWidget(QLabel("Zoom Sensitivity (Scroll Wheel):"))
        self.zoom_spin = QDoubleSpinBox()
        self.zoom_spin.setRange(1.01, 3.0)
        self.zoom_spin.setSingleStep(0.1)
        self.zoom_spin.setValue(get_setting("plotter_zoom_sensitivity", 1.2))
        zoom_layout.addWidget(self.zoom_spin)
        zoom_layout.addStretch()
        plot_layout.addWidget(zoom_group)

        color_group = QGroupBox("Channel Colors")
        color_layout = QVBoxLayout(color_group)
        self.color_luma = get_setting("plotter_color_luma", "#00ff00")
        self.color_cb = get_setting("plotter_color_cb", "#0088ff")
        self.color_cr = get_setting("plotter_color_cr", "#ff3333")
        self.luma_preview = self._create_color_row(
            color_layout, "Luma (Y):", self.color_luma, self._pick_color_luma
        )
        self.cb_preview = self._create_color_row(
            color_layout, "Chroma (Cb):", self.color_cb, self._pick_color_cb
        )
        self.cr_preview = self._create_color_row(
            color_layout, "Chroma (Cr):", self.color_cr, self._pick_color_cr
        )
        plot_layout.addWidget(color_group)

        plot_layout.addStretch()
        self.tabs.addTab(self.tab_plotter, "Plotter")

        # --- PERFORMANCE TAB ---
        self.tab_perf = QWidget()
        perf_layout = QVBoxLayout(self.tab_perf)
        perf_layout.setSpacing(15)

        sys_cores = os.cpu_count() or 1

        wrk_group = QGroupBox("Multiprocessing")
        wrk_layout = QHBoxLayout(wrk_group)
        wrk_layout.addWidget(QLabel("Max Workers (Timeline Render):"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, sys_cores * 2)
        self.workers_spin.setValue(get_setting("timeline_max_workers", sys_cores))
        wrk_layout.addWidget(self.workers_spin)
        wrk_layout.addStretch()
        perf_layout.addWidget(wrk_group)

        cache_group = QGroupBox("Memory")
        cache_layout = QVBoxLayout(cache_group)
        ch_layout = QHBoxLayout()
        ch_layout.addWidget(QLabel("Grain Simulation Cache Size:"))
        self.cache_spin = QSpinBox()
        self.cache_spin.setRange(16, 8192)
        self.cache_spin.setValue(get_setting("fgs_grain_cache_size", 128))
        ch_layout.addWidget(self.cache_spin)
        ch_layout.addStretch()
        cache_layout.addLayout(ch_layout)
        warn_lbl = QLabel("⚠ Requires application restart to take effect.")
        warn_lbl.setStyleSheet("color: #aa6600; font-size: 11px;")
        cache_layout.addWidget(warn_lbl)
        perf_layout.addWidget(cache_group)

        undo_group = QGroupBox("Undo/Redo")
        undo_layout = QVBoxLayout(undo_group)
        uh_layout = QHBoxLayout()
        uh_layout.addWidget(QLabel("Stack Size (Max Steps):"))
        self.undo_spin = QSpinBox()
        self.undo_spin.setRange(10, 1000)
        self.undo_spin.setValue(get_setting("undo_stack_size", 100))
        uh_layout.addWidget(self.undo_spin)
        uh_layout.addStretch()
        undo_layout.addLayout(uh_layout)
        warn_lbl2 = QLabel("⚠ Requires application restart to take effect.")
        warn_lbl2.setStyleSheet("color: #aa6600; font-size: 11px;")
        undo_layout.addWidget(warn_lbl2)
        perf_layout.addWidget(undo_group)

        perf_layout.addStretch()
        self.tabs.addTab(self.tab_perf, "Performance")

        # --- BUTTONS ---
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Apply")
        cancel_btn = QPushButton("Cancel")
        save_btn.clicked.connect(self.save_and_close)
        cancel_btn.clicked.connect(self.reject)
        save_btn.setDefault(True)

        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        main_layout.addLayout(btn_layout)

        # Track initial performance settings to know if restart is needed
        self._initial_perf = {
            "workers": self.workers_spin.value(),
            "cache": self.cache_spin.value(),
            "undo": self.undo_spin.value(),
        }

    def _create_color_row(self, parent_layout, label_text, initial_color, callback):
        row = QHBoxLayout()
        row.addWidget(QLabel(label_text))
        preview = QFrame()
        preview.setFixedSize(24, 24)
        preview.setStyleSheet(
            f"background-color: {initial_color}; border: 1px solid #555;"
        )
        row.addWidget(preview)
        btn = QPushButton("Choose Color...")
        btn.clicked.connect(callback)
        row.addWidget(btn)
        row.addStretch()
        parent_layout.addLayout(row)
        return preview

    def _pick_color_luma(self):
        c = QColorDialog.getColor(QColor(self.color_luma), self, "Select Luma Color")
        if c.isValid():
            self.color_luma = c.name()
            self.luma_preview.setStyleSheet(
                f"background-color: {self.color_luma}; border: 1px solid #555;"
            )

    def _pick_color_cb(self):
        c = QColorDialog.getColor(QColor(self.color_cb), self, "Select Cb Color")
        if c.isValid():
            self.color_cb = c.name()
            self.cb_preview.setStyleSheet(
                f"background-color: {self.color_cb}; border: 1px solid #555;"
            )

    def _pick_color_cr(self):
        c = QColorDialog.getColor(QColor(self.color_cr), self, "Select Cr Color")
        if c.isValid():
            self.color_cr = c.name()
            self.cr_preview.setStyleSheet(
                f"background-color: {self.color_cr}; border: 1px solid #555;"
            )

    def _browse_exe(self, line_edit, exe_name):
        is_win = sys.platform == "win32"
        filter_str = (
            f"{exe_name}.exe (*.exe);;All Files (*)" if is_win else "All Files (*)"
        )
        path, _ = QFileDialog.getOpenFileName(
            self, f"Select {exe_name} executable", "", filter_str
        )
        if path:
            line_edit.setText(os.path.normpath(path))

    def save_and_close(self):
        # Check if performance settings changed
        perf_changed = (
            self._initial_perf["workers"] != self.workers_spin.value()
            or self._initial_perf["cache"] != self.cache_spin.value()
            or self._initial_perf["undo"] != self.undo_spin.value()
        )

        if perf_changed:
            reply = QMessageBox.warning(
                self,
                "Restart Required",
                "You have changed performance settings that require a restart to take effect.\n\n"
                "Before confirming, make sure you have saved your work!\n\n"
                "Do you want to restart the application now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return  # Abort save, stay in dialog

        # Proceed to save
        set_setting("grav1synth_path", self.grav1synth_input.text().strip())
        set_setting("ffmpeg_path", self.ffmpeg_input.text().strip())
        set_setting("ffprobe_path", self.ffprobe_input.text().strip())
        set_setting("default_fps", self.fps_combo.currentText())
        set_setting("default_time_format", self.time_combo.currentText())
        set_setting("show_unsafe_warnings", self.warnings_check.isChecked())

        set_setting("autosave_interval_minutes", self.autosave_spin.value())
        set_setting("fallback_export_frames", self.fallback_spin.value())

        set_setting("plotter_zoom_sensitivity", self.zoom_spin.value())
        set_setting("plotter_color_luma", self.color_luma)
        set_setting("plotter_color_cb", self.color_cb)
        set_setting("plotter_color_cr", self.color_cr)

        set_setting("timeline_max_workers", self.workers_spin.value())
        set_setting("fgs_grain_cache_size", self.cache_spin.value())
        set_setting("undo_stack_size", self.undo_spin.value())

        if perf_changed:
            self._restart_app()
        else:
            QMessageBox.information(
                self, "Settings Saved", "Settings have been saved successfully."
            )
            self.accept()

    def _restart_app(self):
        QApplication.quit()
        QProcess.startDetached(sys.executable, sys.argv)
