import os
import copy
from collections import deque
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
    QDialog,
    QCheckBox,
)
from PySide6.QtCore import Qt

from . import fgs_parser
from . import fgs_math
from .app_paths import get_base_dir
from .plotter import InteractiveFGSPlotter
from .grain_preview import GrainPreviewPlotter
from .params_sidebar import ParamsSidebar
from .shortcuts import create_standard_menu, show_credits, open_github, show_notice
from .panels.tabs_widget import SettingsTabsBar


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

        self.open_video_btn = QPushButton("Open Video")
        self.open_video_btn.setObjectName("bigButton")
        self.open_video_btn.setFixedSize(320, 80)
        self.open_video_btn.clicked.connect(self.main_ui.load_video_dialog)
        layout.addWidget(self.open_video_btn, alignment=Qt.AlignCenter)

        self.create_btn = QPushButton("Create FGS")
        self.create_btn.setObjectName("bigButton")
        self.create_btn.setFixedSize(320, 80)

        create_menu = QMenu(self.create_btn)
        create_menu.addAction("Single Event (Static FGS)").triggered.connect(
            self.main_ui.create_static_fgs
        )
        create_menu.addAction("Multiple Event (TODO)").triggered.connect(
            lambda: print("Dummy: Multiple Event")
        )
        self.create_btn.setMenu(create_menu)

        layout.addWidget(self.create_btn, alignment=Qt.AlignCenter)

        drop_label = QLabel("Or drag and drop an FGS .txt or AV1 video file here")
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

        dot_label2 = QLabel(" • ")
        dot_label2.setStyleSheet("color: #555555; background-color: transparent;")
        bottom_layout.addWidget(dot_label2)

        self.notice_btn = QPushButton("Licenses && Copyright")
        self.notice_btn.setStyleSheet(
            "background-color: transparent; color: #4da6ff; text-decoration: underline; border: none; font-weight: normal; margin-left: 10px;"
        )
        self.notice_btn.setCursor(Qt.PointingHandCursor)
        self.notice_btn.clicked.connect(self.show_notice)
        bottom_layout.addWidget(self.notice_btn)

        layout.addLayout(bottom_layout)

    def show_credits(self):
        show_credits(self)

    def open_github(self):
        open_github()

    def show_notice(self):
        show_notice(self)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            filepath = urls[0].toLocalFile()
            ext = os.path.splitext(filepath)[1].lower()
            if ext == ".txt":
                self.main_ui.load_file_from_path(filepath)
            elif ext == ".mkv":
                self.main_ui.load_video(filepath)


class MainUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FGSEditor")
        self.setMinimumSize(1000, 650)

        self.filepath = None
        self.original_data = {}
        self.current_data = {}
        self.original_p_params = {}
        self.original_grain_size = "-1"
        self.original_time_bounds = (0, 0)
        self._current_event = None

        # Video integration state
        self._video_path: str | None = None
        self._video_info: dict | None = None

        self._undo_stack = deque(maxlen=100)
        self._redo_stack = deque(maxlen=100)
        self._last_known_state = None

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
        self.validation_warning_label.setStyleSheet(
            "color: #ff4444; font-weight: bold; background: #220000; padding: 2px 6px; border-radius: 4px;"
        )
        self.validation_warning_label.hide()
        mid_layout.addWidget(self.validation_warning_label)

        self.save_btn = QPushButton("Save FGS")
        self.save_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.save_btn.clicked.connect(self.save_file)
        self.save_btn.setEnabled(False)
        mid_layout.addWidget(self.save_btn)

        self.save_apply_btn = QPushButton("Save && Apply")
        self.save_apply_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.save_apply_btn.clicked.connect(self.save_and_apply)
        self.save_apply_btn.setEnabled(False)
        self.save_apply_btn.setVisible(False)
        self.save_apply_btn.setToolTip(
            "Save the FGS and apply it to the source video using grav1synth"
        )
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
        self.save_plot_btn.clicked.connect(self.save_plot_as_png)
        mid_layout.addWidget(self.save_plot_btn)

        editor_outer.addWidget(mid_frame)

        self.tabs_bar = SettingsTabsBar()
        editor_outer.addWidget(self.tabs_bar)

        h_splitter = QSplitter(Qt.Horizontal)
        h_splitter.setHandleWidth(4)
        h_splitter.setStyleSheet("QSplitter::handle { background: #333355; }")
        editor_outer.addWidget(h_splitter, stretch=1)

        # Sidebar
        self.sidebar = ParamsSidebar()
        self.tabs_bar.tab_changed.connect(self.sidebar.set_tab)
        self.sidebar.params_changed.connect(self._on_params_changed)
        self.sidebar.grain_size_changed.connect(self._on_grain_size_changed)
        self.sidebar.photon_noise_changed.connect(self._on_photon_noise_changed)
        self.sidebar.template_apply_requested.connect(self._on_template_apply_requested)
        self.sidebar.time_changed.connect(self._on_time_changed)
        h_splitter.addWidget(self.sidebar)

        # Right: vertical splitter (main plot on top, preview on bottom)
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

        # Proportion: main plot 65%, grain preview 35%
        v_splitter.setSizes([420, 220])
        h_splitter.setSizes([320, 680])

    def on_channel_change(self, text):
        self.plotter.set_active_channel(text)

    def on_plotter_changed(self):
        self.current_data = self.plotter.current_data
        self._sync_chromas_if_needed()
        self._refresh_grain_preview()
        self._update_last_known_state()

    def _sync_chromas_if_needed(self):
        p_params = self.sidebar.get_p_params()
        linked = bool(p_params.get("chroma_scaling_from_luma", 0))

        self.plotter.set_chroma_linked(linked)

        if linked:
            # Sync sCb and sCr with sY
            sy = self.current_data.get("sY", {"x": [], "y": []})
            self.current_data["sCb"] = copy.deepcopy(sy)
            self.current_data["sCr"] = copy.deepcopy(sy)

            self.plotter.current_data = copy.deepcopy(self.current_data)
            self.plotter.refresh()

    def _on_params_changed(self, p_params: dict):
        self._push_undo_global()
        if self._current_event is not None:
            self._current_event["p_params"] = p_params

        self._sync_chromas_if_needed()

        self._refresh_grain_preview(p_params=p_params)
        self._update_last_known_state()

    def _on_grain_size_changed(self, size: str):
        self._push_undo_global()
        if self._current_event is not None:
            from .fgs_size_table import apply_grain_preset_to_event

            apply_grain_preset_to_event(self._current_event, size)
            self.sidebar.load_from_event(self._current_event, size_id=size)
        self._refresh_grain_preview(grain_size=size)
        self._update_ui_state()
        self._update_last_known_state()

    def _on_photon_noise_changed(self, payload: dict):
        if not self.current_data:
            return

        if (
            self.current_data["sY"]["x"] == payload["sY"]["x"]
            and self.current_data["sY"]["y"] == payload["sY"]["y"]
        ):
            return

        self._push_undo_global()
        self.current_data["sY"]["x"] = payload["sY"]["x"]
        self.current_data["sY"]["y"] = payload["sY"]["y"]
        self.current_data["sCb"]["x"] = payload["sCb"]["x"]
        self.current_data["sCb"]["y"] = payload["sCb"]["y"]
        self.current_data["sCr"]["x"] = payload["sCr"]["x"]
        self.current_data["sCr"]["y"] = payload["sCr"]["y"]

        self.plotter.current_data = copy.deepcopy(self.current_data)
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
                        self.current_data[ch] = copy.deepcopy(
                            template_evt["scale_data"][ch]
                        )

        if self._current_event:
            if mode in (0, 2):
                new_lines = []
                c_prefixes = ["cY", "cCb", "cCr"]
                tmpl_lines_map = {}
                for line in template_evt.get("raw_lines", []):
                    tokens = line.strip().split()
                    if tokens and tokens[0] in c_prefixes:
                        tmpl_lines_map[tokens[0]] = line

                for line in self._current_event.get("raw_lines", []):
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
                self._current_event["raw_lines"] = new_lines

            if mode == 0:
                if template_evt.get("p_params"):
                    self._current_event["p_params"] = copy.deepcopy(
                        template_evt["p_params"]
                    )

            self.sidebar.load_from_event(self._current_event, size_id="-1")

        self.plotter.current_data = copy.deepcopy(self.current_data)
        self.plotter.refresh()
        self._refresh_grain_preview()
        self._update_ui_state()
        self._update_last_known_state()

    def _update_last_known_state(self):
        self._last_known_state = {
            "data": copy.deepcopy(self.current_data),
            "sidebar": self.sidebar.get_full_state(),
            "event": copy.deepcopy(self._current_event)
            if self._current_event
            else None,
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
        self.current_data = copy.deepcopy(state["data"])
        self._current_event = copy.deepcopy(state.get("event"))
        self.sidebar.set_full_state(state["sidebar"])

        self.plotter.current_data = copy.deepcopy(self.current_data)
        self.plotter.refresh()
        self._refresh_grain_preview()
        self._update_ui_state()
        self._update_last_known_state()

    def redo(self):
        if not self._redo_stack or not self._last_known_state:
            return
        self._undo_stack.append(copy.deepcopy(self._last_known_state))

        state = self._redo_stack.pop()
        self.current_data = copy.deepcopy(state["data"])
        self._current_event = copy.deepcopy(state.get("event"))
        self.sidebar.set_full_state(state["sidebar"])

        self.plotter.current_data = copy.deepcopy(self.current_data)
        self.plotter.refresh()
        self._refresh_grain_preview()
        self._update_ui_state()
        self._update_last_known_state()

    def _refresh_grain_preview(self, p_params=None, grain_size=None):
        if p_params is None:
            p_params = self.sidebar.get_p_params()
        if grain_size is None:
            grain_size = self.sidebar.get_grain_size()

        seed = self.sidebar.get_seed()

        cy_coeffs: list = []
        cb_coeffs: list = []
        cr_coeffs: list = []
        if self._current_event:
            cy_coeffs, cb_coeffs, cr_coeffs = (
                fgs_parser.extract_ar_coeffs_from_raw_lines(
                    self._current_event.get("raw_lines", [])
                )
            )

        self.grain_preview.update_preview(
            self.current_data,
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
        self.plotter.set_clip_extremes(extremes, scaling_shift)
        self.plotter.refresh()

        self._update_ui_state()

    def is_dirty(self) -> bool:
        if not self.filepath:
            return False

        if self.current_data != self.original_data:
            return True
        if self.sidebar.get_p_params() != self.original_p_params:
            return True
        if self.sidebar.get_grain_size() != self.original_grain_size:
            return True
        if self.sidebar.get_event_time_bounds() != self.original_time_bounds:
            return True
        return False

    def _get_validation_errors(self) -> list[str]:
        if not self._current_event:
            return []

        p_params = self.sidebar.get_p_params()
        ar_shift = fgs_parser.get_ar_coeff_shift({"p_params": p_params})

        cy_coeffs, cb_coeffs, cr_coeffs = fgs_parser.extract_ar_coeffs_from_raw_lines(
            self._current_event.get("raw_lines", [])
        )

        all_errors = []
        for ch, coeffs, ch_key in [
            ("Y", cy_coeffs, "sY"),
            ("Cb", cb_coeffs, "sCb"),
            ("Cr", cr_coeffs, "sCr"),
        ]:
            ys = self.current_data.get(ch_key, {}).get("y", [])

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
        self._video_path = None
        self._video_info = None
        self.current_data = {}
        self.original_data = {}
        self.original_p_params = {}
        self.original_grain_size = "-1"
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._last_known_state = None
        self.plotter.set_data({})
        self.grain_preview.update_preview({})
        self.sidebar.set_video_info(None)
        self.save_apply_btn.setVisible(False)
        self.save_apply_btn.setEnabled(False)
        self.stacked_widget.setCurrentIndex(0)
        self.setWindowTitle("FGSEditor")

    def load_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select FGS file", get_base_dir(), "Text Files (*.txt)"
        )
        if not filename:
            return
        self.load_file_from_path(filename)

    def load_video_dialog(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select AV1 Video",
            get_base_dir(),
            "AV1 Video (*.mkv)",
        )
        if not filename:
            return
        self.load_video(filename)

    def load_video(self, filepath):
        from .video_probe import probe_video
        from . import grav1synth as g1s

        try:
            info = probe_video(filepath)
        except FileNotFoundError as exc:
            QMessageBox.critical(self, "ffprobe Not Found", str(exc))
            return
        except (ValueError, RuntimeError) as exc:
            QMessageBox.critical(self, "Video Error", str(exc))
            return

        self._video_path = filepath
        self._video_info = info

        video_base = os.path.splitext(filepath)[0]
        fgs_path = f"{video_base}_fgs.txt"

        has_fgs = False
        try:
            has_fgs = g1s.inspect_fgs(filepath, fgs_path)
        except FileNotFoundError:
            pass
        except RuntimeError:
            pass

        if has_fgs and os.path.isfile(fgs_path):
            reply = QMessageBox.question(
                self,
                "FGS Found",
                "This video contains an existing Film Grain Synthesis table.\n\n"
                "Do you want to modify it, or create a new one from scratch?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            )
            if reply == QMessageBox.Cancel:
                return
            if reply == QMessageBox.Yes:
                self.load_file_from_path(fgs_path)
                self._setup_video_context(filepath, info)
                return
        else:
            QMessageBox.information(
                self,
                "No FGS Found",
                "No Film Grain Synthesis data was found in this video.\n"
                "You will be taken to the FGS creator.",
            )

        self.create_static_fgs()
        self._setup_video_context(filepath, info)

    def _setup_video_context(self, video_path: str, info: dict):
        self._video_path = video_path
        self._video_info = info
        self.sidebar.set_video_info(info)

        if self._current_event:
            start = self._current_event.get("start_time", 0)
            end = self._current_event.get("end_time", 0)
            if start > 0 or end > 0:
                self.sidebar.set_event_times(start, end)

        from . import grav1synth as g1s

        has_g1s = g1s.get_grav1synth_path() is not None
        self.save_apply_btn.setVisible(True)
        self.save_apply_btn.setEnabled(has_g1s)
        if not has_g1s:
            self.save_apply_btn.setToolTip(
                "grav1synth not found.\n"
                "Place it next to FGSEditor or add it to your system PATH."
            )
        else:
            self.save_apply_btn.setToolTip(
                "Save the FGS and apply it to the source video using grav1synth"
            )

        fname = os.path.basename(video_path)
        self.file_label.setText(f"Editing FGS for: {fname}")
        self._update_ui_state()

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
                parsed = fgs_parser.get_scale_data(event)
                self.original_data = copy.deepcopy(parsed)
                self.current_data = copy.deepcopy(parsed)
                self.save_btn.setEnabled(True)
                self.reset_btn.setEnabled(True)
                self.clear_btn.setEnabled(True)
                self.plotter.set_data(self.current_data)

                # Populate sidebar from event p_params
                if event:
                    self.sidebar.load_from_event(event, size_id=-1)

                # Populate time panel from event times
                if event:
                    start_t = event.get("start_time", 0)
                    end_t = event.get("end_time", 0)
                    if start_t > 0 or end_t > 0:
                        self.sidebar.set_event_times(start_t, end_t)

                # Capture originals for dirty check
                self.original_p_params = self.sidebar.get_p_params()
                self.original_grain_size = self.sidebar.get_grain_size()
                self.original_time_bounds = self.sidebar.get_event_time_bounds()

                self._refresh_grain_preview()
                self.stacked_widget.setCurrentIndex(1)
                self._update_ui_state()
                self._update_last_known_state()
        except Exception as ex:
            QMessageBox.critical(self, "Error", f"An error occurred:\n{str(ex)}")

    def create_static_fgs(self):
        from .fgs_templates import get_system_dir
        import os

        default_path = os.path.join(get_system_dir(), "default.txt")
        if not os.path.isfile(default_path):
            QMessageBox.warning(
                self, "Missing Default", "Could not find Templates/system/default.txt"
            )
            return

        # load as if we opened it, but set no filepath
        self.load_file_from_path(default_path)
        self.filepath = None
        self.file_label.setText("Editing: Unsaved New FGS")
        self._update_ui_state()

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
            self._push_undo_global()
            self.current_data = copy.deepcopy(self.original_data)
            self.plotter.current_data = copy.deepcopy(self.current_data)
            self.plotter.refresh()
            self._refresh_grain_preview()
            self._update_last_known_state()

    def clear_channel(self):
        if not self.current_data:
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
            "QPushButton { background: #5c1a1a; color: #ff6b6b; border: 1px solid #ff4444; "
            "border-radius: 4px; padding: 6px; font-weight: bold; }"
            "QPushButton:hover { background: #7c2a2a; }"
        )

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            "QPushButton { background: #2d2d2d; color: #aaaaaa; border: 1px solid #444; "
            "border-radius: 4px; padding: 6px; }"
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
                self.current_data[ch]["x"] = []
                self.current_data[ch]["y"] = []

            self.plotter.current_data = copy.deepcopy(self.current_data)
            self.plotter.refresh()
            self._refresh_grain_preview()
            self._update_last_known_state()
            self._update_ui_state()

    def _on_time_changed(self, start_ticks: int, end_ticks: int):
        if self._current_event is not None:
            self._push_undo_global()
            self._current_event["start_time"] = start_ticks
            self._current_event["end_time"] = end_ticks
            self._update_ui_state()
            self._update_last_known_state()

    def save_file(self):
        if not self.filepath:
            return

        start_t, end_t = None, None
        # Sync times from the Time panel
        if self._current_event is not None:
            start_t, end_t = self.sidebar.get_event_time_bounds()
            self._current_event["start_time"] = start_t
            self._current_event["end_time"] = end_t

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

        p_params = self.sidebar.get_p_params() if self._current_event else None
        event_raw_lines = (
            self._current_event.get("raw_lines") if self._current_event else None
        )
        from .fgs_save import save_static_fgs

        default_name = "modified_fgs.txt"
        if self._video_path:
            video_base = os.path.splitext(os.path.basename(self._video_path))[0]
            default_name = f"{video_base}.txt"

        saved = save_static_fgs(
            self,
            original_filepath=self.filepath,
            scale_data=self.current_data,
            p_params=p_params,
            event_raw_lines=event_raw_lines,
            start_time=start_t,
            end_time=end_t,
            default_name=default_name,
        )

        if saved:
            self.original_data = copy.deepcopy(self.current_data)
            self.original_p_params = self.sidebar.get_p_params()
            self.original_grain_size = self.sidebar.get_grain_size()
            self.original_time_bounds = self.sidebar.get_event_time_bounds()
            self._update_ui_state()
            self._update_last_known_state()
        self._update_ui_state()

    def save_and_apply(self):
        if not self._video_path:
            QMessageBox.warning(self, "No Video", "No source video loaded.")
            return

        from . import grav1synth as g1s

        exe = g1s.get_grav1synth_path()
        if exe is None:
            QMessageBox.critical(
                self,
                "grav1synth Not Found",
                "grav1synth was not found.\n\n"
                "Place the binary next to FGSEditor or add it to your system PATH.",
            )
            return

        # Sync times
        if self._current_event is not None:
            start_t, end_t = self.sidebar.get_event_time_bounds()
            self._current_event["start_time"] = start_t
            self._current_event["end_time"] = end_t

        # Validation
        errors = self._get_validation_errors()
        if errors:
            error_text = "\n".join(errors)
            reply = QMessageBox.warning(
                self,
                "Unsafe Preset",
                f"The current preset has stability or clipping issues:\n\n{error_text}\n\nAre you sure you want to continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return

        # Ask for output video path
        src_base = os.path.splitext(os.path.basename(self._video_path))
        src_ext = src_base[1] if len(src_base) > 1 else ".mkv"
        default_out = os.path.join(
            os.path.dirname(self._video_path),
            f"{src_base[0]}_applied{src_ext}",
        )
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Output Video",
            default_out,
            "MKV Video (*.mkv);;All Files (*)",
        )
        if not output_path:
            return

        # Save FGS to a file next to the input video so the user can inspect it
        import tempfile

        if self._video_path:
            video_dir = os.path.dirname(self._video_path)
            video_base = os.path.splitext(os.path.basename(self._video_path))[0]
            candidate = os.path.join(video_dir, f"{video_base}.txt")
            idx = 0
            # find a non-conflicting filename
            while os.path.exists(candidate):
                idx += 1
                candidate = os.path.join(video_dir, f"{video_base} ({idx}).txt")
            tmp_fgs = candidate
        else:
            tmp_dir = tempfile.mkdtemp(prefix="fgseditor_apply_")
            tmp_fgs = os.path.join(tmp_dir, "grain_table.txt")

        # Build the FGS content
        p_params = self.sidebar.get_p_params() if self._current_event else None
        event_raw_lines = (
            self._current_event.get("raw_lines") if self._current_event else None
        )

        source_fgs = self.filepath
        if not source_fgs:
            from .fgs_templates import get_system_dir

            source_fgs = os.path.join(get_system_dir(), "default.txt")

        from .fgs_save import build_static_lines

        try:
            with open(source_fgs, "r", encoding="utf-8") as fh:
                original_lines = fh.readlines()

            if event_raw_lines is not None:
                header_and_e = []
                for line in original_lines:
                    header_and_e.append(line)
                    tokens = line.strip().split()
                    if tokens and tokens[0] == "E":
                        break
                original_lines = header_and_e + event_raw_lines

            if self._current_event is not None:
                from .time_utils import seconds_to_ticks

                start_t = self._current_event.get("start_time", 0)
                end_t = self._current_event.get("end_time", 0)
                if self._video_path:
                    end_t += seconds_to_ticks(10.0)
                updated_lines = []
                for line in original_lines:
                    tokens = line.strip().split()
                    if tokens and tokens[0] == "E" and len(tokens) >= 3:
                        extra = " ".join(tokens[3:]) if len(tokens) > 3 else ""
                        line = f"E {start_t} {end_t}"
                        if extra:
                            line += f" {extra}"
                        line += "\n"
                    updated_lines.append(line)
                original_lines = updated_lines

            new_lines = build_static_lines(original_lines, self.current_data, p_params)

            with open(tmp_fgs, "w", encoding="utf-8") as fh:
                fh.writelines(new_lines)
        except Exception as ex:
            QMessageBox.critical(self, "Error", f"Failed to build FGS file:\n{ex}")
            return

        from PySide6.QtWidgets import QProgressDialog

        progress = QProgressDialog(
            "Applying film grain to video...\nThis may take a while.",
            None,
            0,
            0,
            self,
        )
        progress.setWindowTitle("Applying FGS")
        progress.setMinimumDuration(0)
        progress.show()
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()

        success, msg = g1s.apply_fgs(self._video_path, tmp_fgs, output_path)
        progress.close()

        if success:
            QMessageBox.information(
                self,
                "Success",
                f"Film grain applied successfully!\n\nOutput: {output_path}\nFGS saved to: {tmp_fgs}",
            )
        else:
            QMessageBox.critical(
                self,
                "Apply Failed",
                f"Failed to apply film grain:\n\n{msg}\n\nFGS used: {tmp_fgs}",
            )

    def save_plot_as_png(self):
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Plot as PNG",
            os.path.join(get_base_dir(), "plot.png"),
            "PNG Images (*.png)",
        )
        if not save_path:
            return

        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 4), dpi=100)
        plt.style.use("dark_background")

        ax.set_facecolor("#111111")
        styles = {
            "sY": {"color": "#2ca02c", "label": "Luma (sY)", "marker": "o"},
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
