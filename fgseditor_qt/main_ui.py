import os
import copy
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QComboBox,
    QFileDialog,
    QMessageBox,
    QSizePolicy,
    QFrame,
    QStackedWidget,
    QMenu,
    QSplitter,
)
from PySide6.QtCore import Qt

from . import fgs_parser
from .app_paths import get_base_dir
from .plotter import InteractiveFGSPlotter
from .grain_preview import GrainPreviewPlotter
from .params_sidebar import ParamsSidebar
from .shortcuts import create_standard_menu, show_credits, open_github


class WelcomeScreen(QFrame):
    def __init__(self, main_ui):
        super().__init__()
        self.main_ui = main_ui
        self.setAcceptDrops(True)
        self.setObjectName("welcomeScreen")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(20)

        self.open_btn = QPushButton("Open FGS File")
        self.open_btn.setObjectName("bigButton")
        self.open_btn.setFixedSize(320, 80)
        self.open_btn.clicked.connect(self.main_ui.load_file)
        layout.addWidget(self.open_btn, alignment=Qt.AlignCenter)

        self.create_btn = QPushButton("Create FGS")
        self.create_btn.setObjectName("bigButton")
        self.create_btn.setFixedSize(320, 80)

        create_menu = QMenu(self.create_btn)
        create_menu.addAction("Single Event (TODO)").triggered.connect(
            lambda: print("Dummy: Single Event")
        )
        create_menu.addAction("Multiple Event (TODO)").triggered.connect(
            lambda: print("Dummy: Multiple Event")
        )
        self.create_btn.setMenu(create_menu)

        layout.addWidget(self.create_btn, alignment=Qt.AlignCenter)

        drop_label = QLabel("Or drag and drop an FGS .txt file here")
        drop_label.setAlignment(Qt.AlignCenter)
        drop_label.setStyleSheet("color: #777777; font-size: 15px; margin-top: 15px;")
        layout.addWidget(drop_label, alignment=Qt.AlignCenter)

        layout.addSpacing(40)

        bottom_layout = QHBoxLayout()
        bottom_layout.setAlignment(Qt.AlignCenter)

        self.credits_btn = QPushButton("Credits")
        self.credits_btn.setStyleSheet(
            "background-color: transparent; color: #4da6ff; text-decoration: underline; border: none; font-weight: normal;"
        )
        self.credits_btn.setCursor(Qt.PointingHandCursor)
        self.credits_btn.clicked.connect(self.show_credits)
        bottom_layout.addWidget(self.credits_btn)

        dot_label = QLabel(" • ")
        dot_label.setStyleSheet("color: #555555; background-color: transparent;")
        bottom_layout.addWidget(dot_label)

        self.github_btn = QPushButton("GitHub")
        self.github_btn.setStyleSheet(
            "background-color: transparent; color: #4da6ff; text-decoration: underline; border: none; font-weight: normal;"
        )
        self.github_btn.setCursor(Qt.PointingHandCursor)
        self.github_btn.clicked.connect(self.open_github)
        bottom_layout.addWidget(self.github_btn)

        layout.addLayout(bottom_layout)

    def show_credits(self):
        show_credits(self)

    def open_github(self):
        open_github()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            filepath = urls[0].toLocalFile()
            if filepath.endswith(".txt"):
                self.main_ui.load_file_from_path(filepath)


class MainUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FGSEditor")
        self.setMinimumSize(1000, 650)

        self.filepath = None
        self.original_data = {}
        self.current_data = {}
        self.original_p_params = {}
        self.original_grain_size = 0
        self._current_event = None

        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)

        self.welcome_screen = WelcomeScreen(self)
        self.stacked_widget.addWidget(self.welcome_screen)

        self.editor_widget = QWidget()
        editor_outer = QVBoxLayout(self.editor_widget)
        editor_outer.setContentsMargins(0, 0, 0, 0)
        editor_outer.setSpacing(0)
        self.stacked_widget.addWidget(self.editor_widget)

        # Top bar
        top_frame = QFrame()
        top_frame.setObjectName("toolbar")
        top_layout = QHBoxLayout(top_frame)
        top_layout.setContentsMargins(10, 6, 10, 6)

        self.close_btn = QPushButton("Close FGS")
        self.close_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.close_btn.clicked.connect(self.close_fgs)
        top_layout.addWidget(self.close_btn, stretch=0)

        self.file_label = QLabel("No file selected")
        self.file_label.setWordWrap(True)
        top_layout.addWidget(self.file_label, stretch=1)

        editor_outer.addWidget(top_frame)

        menu_bar = create_standard_menu(self)
        editor_outer.setMenuBar(menu_bar)

        # Middle controls bar
        mid_frame = QFrame()
        mid_frame.setObjectName("toolbar")
        mid_layout = QHBoxLayout(mid_frame)
        mid_layout.setContentsMargins(10, 4, 10, 4)

        mid_layout.addWidget(QLabel("Channel:"), stretch=0)
        self.channel_dropdown = QComboBox()
        self.channel_dropdown.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.channel_dropdown.addItems(["sY", "sCb", "sCr"])
        self.channel_dropdown.currentTextChanged.connect(self.on_channel_change)
        mid_layout.addWidget(self.channel_dropdown, stretch=0)

        mid_layout.addStretch(1)

        self.validation_warning_label = QLabel()
        self.validation_warning_label.setStyleSheet("color: #ff4444; font-weight: bold; background: #220000; padding: 2px 6px; border-radius: 4px;")
        self.validation_warning_label.hide()
        mid_layout.addWidget(self.validation_warning_label)

        self.save_btn = QPushButton("Save FGS")
        self.save_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.save_btn.clicked.connect(self.save_file)
        self.save_btn.setEnabled(False)
        mid_layout.addWidget(self.save_btn)

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
        self.save_plot_btn.clicked.connect(self.save_plot_as_png)
        mid_layout.addWidget(self.save_plot_btn)

        editor_outer.addWidget(mid_frame)

        h_splitter = QSplitter(Qt.Horizontal)
        h_splitter.setHandleWidth(4)
        h_splitter.setStyleSheet(
            "QSplitter::handle { background: #333355; }"
        )
        editor_outer.addWidget(h_splitter, stretch=1)

        # Sidebar
        self.sidebar = ParamsSidebar()
        self.sidebar.params_changed.connect(self._on_params_changed)
        self.sidebar.grain_size_changed.connect(self._on_grain_size_changed)
        h_splitter.addWidget(self.sidebar)

        # Right: vertical splitter (main plot on top, preview on bottom)
        v_splitter = QSplitter(Qt.Vertical)
        v_splitter.setHandleWidth(4)
        v_splitter.setStyleSheet(
            "QSplitter::handle { background: #333355; }"
        )
        h_splitter.addWidget(v_splitter)

        self.plotter = InteractiveFGSPlotter()
        self.plotter.data_changed.connect(self.on_plotter_changed)
        v_splitter.addWidget(self.plotter)

        self.grain_preview = GrainPreviewPlotter()
        self.grain_preview.setMinimumHeight(130)
        v_splitter.addWidget(self.grain_preview)

        # Proportion: main plot 65%, grain preview 35%
        v_splitter.setSizes([420, 220])
        h_splitter.setSizes([200, 800])

    def on_channel_change(self, text):
        self.plotter.set_active_channel(text)

    def on_plotter_changed(self):
        self.current_data = self.plotter.current_data
        self._refresh_grain_preview()

    def _on_params_changed(self, p_params: dict):
        if self._current_event is not None:
            self._current_event["p_params"] = p_params
        self._refresh_grain_preview(p_params=p_params)

    def _on_grain_size_changed(self, size: int):
        if self._current_event is not None:
            from .fgs_size_table import apply_size_preset_to_event
            apply_size_preset_to_event(self._current_event, size)
            # Sync sidebar UI with the new p_params from the preset, keeping the selected size
            self.sidebar.load_from_event(self._current_event, size_id=size)
        self._refresh_grain_preview(grain_size=size)
        self._update_ui_state()

    def _refresh_grain_preview(self, p_params=None, grain_size=None):
        if p_params is None:
            p_params = self.sidebar.get_p_params()
        if grain_size is None:
            grain_size = self.sidebar.get_grain_size()
        noise_setting = self.sidebar.get_noise_setting()
        autobalance = self.sidebar.get_autobalance()
        # Extract all AR coefficients for luma + chroma AGC
        cy_coeffs: list = []
        cb_coeffs: list = []
        cr_coeffs: list = []
        if self._current_event:
            from .fgs_math import extract_ar_coeffs_from_raw_lines
            cy_coeffs, cb_coeffs, cr_coeffs = extract_ar_coeffs_from_raw_lines(
                self._current_event.get("raw_lines", [])
            )
        self.grain_preview.update_preview(
            self.current_data, p_params=p_params, grain_size=grain_size,
            cy_coeffs=cy_coeffs, cb_coeffs=cb_coeffs, cr_coeffs=cr_coeffs,
            noise_setting=noise_setting, autobalance=autobalance,
        )
        # AR stability warning on the sidebar
        self.sidebar.set_ar_shift_warning(self.grain_preview.is_ar_unstable())
        self._update_ui_state()

    def is_dirty(self) -> bool:
        """Check if any data or parameters have changed from the original markers."""
        if not self.filepath:
            return False
            
        if self.current_data != self.original_data:
            return True
        if self.sidebar.get_p_params() != self.original_p_params:
            return True
        if self.sidebar.get_grain_size() != self.original_grain_size:
            return True
        return False

    def _get_validation_errors(self) -> list[str]:
        if not self._current_event:
            return []
            
        p_params = self.sidebar.get_p_params()
        grain_size = self.sidebar.get_grain_size()
        ar_shift = p_params.get("ar_coeff_shift", 8) if p_params else 8
        autobalance = self.sidebar.get_autobalance()
        
        from .fgs_math import extract_ar_coeffs_from_raw_lines, compute_export_scale_factor, validate_fgs_pipeline
        cy_coeffs, cb_coeffs, cr_coeffs = extract_ar_coeffs_from_raw_lines(self._current_event.get("raw_lines", []))
        
        all_errors = []
        for ch, coeffs, ch_key in [("Y", cy_coeffs, "sY"), ("Cb", cb_coeffs, "sCb"), ("Cr", cr_coeffs, "sCr")]:
            ys = self.current_data.get(ch_key, {}).get("y", [])
            export_scale = compute_export_scale_factor(grain_size, coeffs, ar_shift) if autobalance else 1.0
            
            errors = validate_fgs_pipeline(coeffs, ar_shift, ys, export_scale)
            if errors:
                all_errors.append(f"Channel {ch}:\n" + "\n".join(" - " + e for e in errors))
        
        return all_errors

    def _update_ui_state(self):
        """Update window title and Save button enablement based on dirty state."""
        dirty = self.is_dirty()
        
        errors = self._get_validation_errors()
        if errors:
            self.validation_warning_label.setText("⚠ UNSAFE PRESET")
            self.validation_warning_label.setToolTip("\n\n".join(errors))
            self.validation_warning_label.show()
        else:
            self.validation_warning_label.hide()
            
        self.save_btn.setEnabled(dirty)
        
        title = "FGSEditor"
        if self.filepath:
            import os
            fname = os.path.basename(self.filepath)
            title += f" - {fname}"
        if dirty:
            title += " *"
        self.setWindowTitle(title)

    def closeEvent(self, event):
        if self.is_dirty():
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Do you want to save before exiting?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Save:
                self.save_file()
                event.accept()
            elif reply == QMessageBox.Cancel:
                event.ignore()
                return
        event.accept()

    def close_fgs(self):
        if self.is_dirty():
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
                return

        self.filepath = None
        self._current_event = None
        self.current_data = {}
        self.original_data = {}
        self.original_p_params = {}
        self.original_grain_size = 0
        self.plotter.set_data({})
        self.grain_preview.update_preview({})
        self.stacked_widget.setCurrentIndex(0)
        self.setWindowTitle("FGSEditor")

    def load_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select FGS file", get_base_dir(), "Text Files (*.txt)"
        )
        if not filename:
            return
        self.load_file_from_path(filename)

    def load_file_from_path(self, filepath):
        self.filepath = filepath
        self.file_label.setText(f"Editing: {self.filepath}")

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                content = f.read()

            header_lines, events = fgs_parser.parse_fgs_events(content)

            if fgs_parser.is_dynamic(events):
                from .dynamic_ui import DynamicTimelineUI

                self.dynamic_ui = DynamicTimelineUI(
                    self,
                    {
                        "header_lines": header_lines,
                        "events": events,
                        "filepath": self.filepath,
                    },
                )
                self.hide()
                self.dynamic_ui.show()
            else:
                event = events[0] if events else {}
                self._current_event = event
                parsed = event.get("scale_data", {}) if event else {}
                self.original_data = copy.deepcopy(parsed)
                self.current_data = copy.deepcopy(parsed)
                self.save_btn.setEnabled(True)
                self.reset_btn.setEnabled(True)
                self.clear_btn.setEnabled(True)
                self.plotter.set_data(self.current_data)

                # Populate sidebar from event p_params
                if event:
                    self.sidebar.load_from_event(event, size_id=-1)

                # Capture originals for dirty check
                self.original_p_params = self.sidebar.get_p_params()
                self.original_grain_size = self.sidebar.get_grain_size()

                self._refresh_grain_preview()
                self.stacked_widget.setCurrentIndex(1)
                self._update_ui_state()
        except Exception as ex:
            QMessageBox.critical(self, "Error", f"An error occurred:\n{str(ex)}")

    def reset_data(self):
        if not self.original_data:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Reset",
            "Are you sure you want to revert all changes?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.current_data = copy.deepcopy(self.original_data)
            self.plotter.set_data(self.current_data)
            self._refresh_grain_preview()

    def clear_channel(self):
        if not self.current_data:
            return

        ch = self.channel_dropdown.currentText()
        reply = QMessageBox.question(
            self,
            "Confirm Clear",
            f"Are you sure you want to remove all points from {ch}?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.current_data[ch]["x"] = []
            self.current_data[ch]["y"] = []
            self.plotter.set_data(self.current_data)
            self._refresh_grain_preview()

    def save_file(self):
        if not self.filepath:
            return
            
        errors = self._get_validation_errors()
        if errors:
            error_text = "\n".join(errors)
            reply = QMessageBox.warning(
                self, 
                "Unsafe Preset", 
                f"The current preset has stability or clipping issues:\n\n{error_text}\n\nAre you sure you want to save anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
        
        p_params = self.sidebar.get_p_params() if self._current_event else None
        from .fgs_save import save_static_fgs
        saved = save_static_fgs(
            self,
            original_filepath=self.filepath,
            scale_data=self.current_data,
            p_params=p_params,
            grain_size=self.sidebar.get_grain_size(),
            autobalance=self.sidebar.get_autobalance(),
        )
        
        if saved:
            self.original_data = copy.deepcopy(self.current_data)
            self.original_p_params = self.sidebar.get_p_params()
            self.original_grain_size = self.sidebar.get_grain_size()
            self._update_ui_state()
        self._update_ui_state()

    def save_plot_as_png(self):
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save Plot as PNG", os.path.join(get_base_dir(), "plot.png"), "PNG Images (*.png)"
        )
        if not save_path:
            return

        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 4), dpi=100)
        plt.style.use("dark_background")

        ax.set_facecolor("#111111")
        styles = {
            "sY":  {"color": "#2ca02c", "label": "Luma (sY)",    "marker": "o"},
            "sCb": {"color": "#1f77b4", "label": "Chroma (sCb)", "marker": "s"},
            "sCr": {"color": "#d62728", "label": "Chroma (sCr)", "marker": "^"},
        }

        min_y = float("inf")
        max_y = 0
        has_data = False

        for channel, data in self.current_data.items():
            if data["x"]:
                has_data = True
                min_y = min(min_y, min(data["y"]))
                max_y = max(max_y, max(data["y"]))
                ax.plot(
                    data["x"],
                    data["y"],
                    color=styles[channel]["color"],
                    label=styles[channel]["label"],
                    marker=styles[channel]["marker"],
                    linestyle="-",
                    markersize=6,
                    linewidth=2,
                )

        ax.set_title("Film Grain Strength - Saved Plot")
        ax.set_xlabel("Y Value")
        ax.set_ylabel("Strength (0-255)")
        ax.grid(True, linestyle="--", color="#444444", alpha=0.5)

        if has_data:
            y_margin = max(5, (max_y - min_y) * 0.15)
            ax.legend()
            ax.set_xlim(0, 255)
            ax.set_ylim(min_y - y_margin, max_y + y_margin)
            ax.set_xticks([0, 16, 50, 100, 150, 200, 235, 255])
            ax.axvline(16, color="#555555", linestyle=":", alpha=0.5)
            ax.axvline(235, color="#555555", linestyle=":", alpha=0.5)
            ax.axhline(100, color="#f59e0b", linestyle=":", alpha=0.35, linewidth=0.9)

        fig.savefig(save_path, dpi=300, bbox_inches="tight")
        plt.close(fig)

        QMessageBox.information(self, "Success", f"Plot saved to:\n{save_path}")
