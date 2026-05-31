import os
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFileDialog,
    QMessageBox,
    QFrame,
    QStackedWidget,
    QMenu,
    QDialog,
)
from PySide6.QtCore import Qt

from . import fgs_parser
from .app_paths import get_base_dir
from .shortcuts import create_standard_menu, show_credits, open_github, show_notice
from .single_editor import SingleEventEditor


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
        self._current_event = None

        # Video integration state
        self._video_path: str | None = None
        self._video_info: dict | None = None

        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)

        self.welcome_screen = WelcomeScreen(self)
        self.stacked_widget.addWidget(self.welcome_screen)

        self.editor_widget = QWidget()
        editor_outer = QVBoxLayout(self.editor_widget)
        editor_outer.setContentsMargins(0, 0, 0, 0)
        editor_outer.setSpacing(0)
        self.stacked_widget.addWidget(self.editor_widget)

        menu_bar = create_standard_menu(self)
        editor_outer.setMenuBar(menu_bar)

        self.editor = SingleEventEditor(is_dynamic=False, parent=self)
        editor_outer.addWidget(self.editor)

        self.editor.close_fgs_requested.connect(self.close_fgs)
        self.editor.save_fgs_requested.connect(self.save_file)
        self.editor.save_bin_requested.connect(self.save_binary_file)
        self.editor.save_apply_requested.connect(self.save_and_apply)
        self.editor.save_plot_requested.connect(self.save_plot_as_png)
        self.editor.state_changed.connect(self._on_state_changed)

    def _on_state_changed(self, dirty: bool):
        self.editor.set_save_bin_enabled(self.filepath is not None or dirty)

        title = "FGSEditor"
        if self.filepath:
            fname = os.path.basename(self.filepath)
            title += f" - {fname}"
        if dirty:
            title += " *"
        self.setWindowTitle(title)

    def closeEvent(self, event):
        if self.editor.is_dirty():
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
        if self.editor.is_dirty():
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
        self.editor.close_plotters()
        self.editor.load_event(None)
        self.editor.set_video_info(None)
        self.editor.set_save_apply_enabled(False)
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
            "Select Supported Video",
            get_base_dir(),
            "Video Files (*.mkv *.ivf *.mp4 *.hevc);;All Files (*)",
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

        is_hevc = info.get("codec", "").lower() == "hevc"

        has_fgs = False
        if not is_hevc:
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
                "If you want to edit it, press Yes. Otherwise, press No to create a new one.",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            )
            if reply == QMessageBox.Cancel:
                return
            if reply == QMessageBox.Yes:
                self.load_file_from_path(fgs_path)
                self._setup_video_context(filepath, info)
                return
        else:
            if not is_hevc:
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
        self.editor.set_video_info(info)

        from . import grav1synth as g1s

        is_hevc = info.get("codec", "").lower() == "hevc"
        has_g1s = g1s.get_grav1synth_path() is not None
        
        if is_hevc:
            self.editor.set_save_apply_enabled(
                False,
                "Save & Apply is not available for HEVC videos. It only works on AV1 videos."
            )
        elif not has_g1s:
            self.editor.set_save_apply_enabled(
                True,
                "grav1synth not found.\nPlace it next to FGSEditor or add it to your system PATH.",
            )
        else:
            self.editor.set_save_apply_enabled(
                True, "Save the FGS and apply it to the source video using grav1synth"
            )

        fname = os.path.basename(video_path)
        self.editor.set_file_label(f"Editing FGS for: {fname}")
        self._on_state_changed(self.editor.is_dirty())

    def load_file_from_path(self, filepath):
        self.filepath = filepath
        self.editor.set_file_label(f"Editing: {self.filepath}")

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
                self.editor.load_event(event)
                self.stacked_widget.setCurrentIndex(1)
                self._on_state_changed(False)
        except Exception as ex:
            QMessageBox.critical(self, "Error", f"An error occurred:\n{str(ex)}")

    def create_static_fgs(self):
        from .fgs_templates import get_system_dir

        default_path = os.path.join(get_system_dir(), "default.txt")
        if not os.path.isfile(default_path):
            QMessageBox.warning(
                self, "Missing Default", "Could not find Templates/system/default.txt"
            )
            return

        self.load_file_from_path(default_path)
        self.filepath = None
        self.editor.set_file_label("Editing: Unsaved New FGS")
        self._on_state_changed(True)

    def save_file(self):
        start_t, end_t = self.editor.get_event_time_bounds()
        if self._current_event:
            self._current_event["start_time"] = start_t
            self._current_event["end_time"] = end_t

        if not self.filepath:
            pass  # Keep default behaviors later on

        errors = self.editor.get_validation_errors()
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
                return False

        p_params = self.editor.get_p_params()
        self.editor.apply_working_to_event()
        event_raw_lines = (
            self._current_event.get("raw_lines") if self._current_event else None
        )
        from .fgs_save import save_static_fgs

        default_name = "modified_fgs.txt"
        if self._video_path:
            video_base = os.path.splitext(os.path.basename(self._video_path))[0]
            default_name = f"{video_base}.txt"

        force_path = self.filepath
        if self.filepath:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Save Options")
            msg_box.setText(
                f"File already exists:\n{os.path.basename(self.filepath)}\n\nDo you want to overwrite it or save as a new file?"
            )

            overwrite_btn = msg_box.addButton("Overwrite", QMessageBox.AcceptRole)
            save_as_btn = msg_box.addButton("Save As...", QMessageBox.ActionRole)
            cancel_btn = msg_box.addButton(QMessageBox.Cancel)

            msg_box.setDefaultButton(overwrite_btn)
            msg_box.exec()

            if msg_box.clickedButton() == cancel_btn:
                return False
            if msg_box.clickedButton() == save_as_btn:
                force_path = None

        saved_path = save_static_fgs(
            self,
            original_filepath=self.filepath,
            scale_data=self.editor.current_scale_data,
            p_params=p_params,
            event_raw_lines=event_raw_lines,
            start_time=start_t,
            end_time=end_t,
            grain_seed=self.editor.get_seed(),
            default_name=default_name,
            force_path=force_path,
        )

        if saved_path:
            self.filepath = saved_path
            self.editor.set_file_label(f"Editing: {os.path.basename(self.filepath)}")
            self._on_state_changed(False)
            return True
        self._on_state_changed(self.editor.is_dirty())
        return False

    def save_binary_file(self):
        # Always save the .txt file first before generating binary
        if not self.save_file():
            return

        if self.editor.is_dirty() or not self.filepath:
            return

        from PySide6.QtWidgets import QFileDialog, QMessageBox

        # Determine num_frames based on video info or UI
        if hasattr(self, "_video_info") and self._video_info:
            fps = self._video_info.get("fps", 0)
            dur_s = self._video_info.get("duration_s", 0)
            if fps > 0 and dur_s > 0:
                num_frames = int(dur_s * fps)
            else:
                from .settings_manager import get_setting
                num_frames = get_setting("fallback_export_frames", 150000)
                fps = 24.0
        else:
            fps = 24.0
            start_t, end_t = self.editor.get_event_time_bounds()
            dur_s = (end_t - start_t) / 10000000.0
            if fps > 0 and dur_s > 0:
                num_frames = int(dur_s * fps)
            else:
                from .settings_manager import get_setting
                num_frames = get_setting("fallback_export_frames", 150000)
                if fps <= 0:
                    fps = 24.0

        if num_frames <= 0:
            QMessageBox.warning(
                self, "Invalid Duration", "Duration must be greater than 0."
            )
            return

        default_out = os.path.splitext(self.filepath)[0] + ".bin"

        # --- Static / Dynamic choice ---
        mode_dialog = QDialog(self)
        mode_dialog.setWindowTitle("Binary Export Mode")
        mode_dialog.setMinimumWidth(420)
        _md_layout = QVBoxLayout(mode_dialog)
        _md_layout.setSpacing(12)

        _md_title = QLabel("<b>Choose the binary export mode:</b>")
        _md_title.setTextFormat(Qt.RichText)
        _md_layout.addWidget(_md_title)

        _md_static_desc = QLabel(
            "<b>Static</b> — Every frame uses the same seed.\n"
            "Grain pattern repeats identically on every frame."
        )
        _md_static_desc.setWordWrap(True)
        _md_layout.addWidget(_md_static_desc)

        _md_dynamic_desc = QLabel(
            "<b>Dynamic</b> — A different seed is chosen for each frame\n"
            "from the curated seed list."
        )
        _md_dynamic_desc.setWordWrap(True)
        _md_layout.addWidget(_md_dynamic_desc)

        _md_btn_layout = QHBoxLayout()
        _md_static_btn = QPushButton("Static")
        _md_dynamic_btn = QPushButton("Dynamic")
        _md_cancel_btn = QPushButton("Cancel")
        _md_btn_layout.addWidget(_md_static_btn)
        _md_btn_layout.addWidget(_md_dynamic_btn)
        _md_btn_layout.addWidget(_md_cancel_btn)
        _md_layout.addLayout(_md_btn_layout)

        _md_result = [None]  # mutable container

        def _pick_static():
            _md_result[0] = True
            mode_dialog.accept()

        def _pick_dynamic():
            _md_result[0] = False
            mode_dialog.accept()

        _md_static_btn.clicked.connect(_pick_static)
        _md_dynamic_btn.clicked.connect(_pick_dynamic)
        _md_cancel_btn.clicked.connect(mode_dialog.reject)

        if mode_dialog.exec() != QDialog.Accepted or _md_result[0] is None:
            return

        static_mode = _md_result[0]
        # --- end Static / Dynamic choice ---

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save AFGS1 Binary Payload",
            default_out,
            "Binary AFGS1 (*.bin)",
        )
        if not output_path:
            return

        from .binary_x265_FGS import parse_and_pack

        try:
            success = parse_and_pack(
                self.filepath,
                output_path,
                fps=fps,
                fallback_frames=num_frames,
                static_mode=static_mode,
            )
            if success:
                mode_label = "Static" if static_mode else "Dynamic"
                QMessageBox.information(
                    self,
                    "Success",
                    f"AFGS1 binary payload saved successfully ({num_frames} frames, {mode_label} mode):\n{output_path}",
                )
            else:
                QMessageBox.critical(self, "Error", "Failed to parse FGS txt file.")
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"An error occurred while generating binary payload:\n{str(e)}",
            )

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
        start_t, end_t = self.editor.get_event_time_bounds()
        if self._current_event is not None:
            self._current_event["start_time"] = start_t
            self._current_event["end_time"] = end_t

        # Validation
        errors = self.editor.get_validation_errors()
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
        video_dir = os.path.dirname(self._video_path)

        base_name_candidate = f"{src_base[0]}_fgs_applied"
        default_out = os.path.join(video_dir, f"{base_name_candidate}{src_ext}")
        idx = 0
        while os.path.exists(default_out) or os.path.exists(
            os.path.join(video_dir, f"{base_name_candidate}.txt")
        ):
            idx += 1
            base_name_candidate = f"{src_base[0]}_fgs_applied ({idx})"
            default_out = os.path.join(video_dir, f"{base_name_candidate}{src_ext}")

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Output Video",
            default_out,
            "MKV Video (*.mkv);;All Files (*)",
        )
        if not output_path:
            return

        out_dir = os.path.dirname(output_path)
        out_base = os.path.splitext(os.path.basename(output_path))[0]
        tmp_fgs = os.path.join(out_dir, f"{out_base}.txt")

        p_params = self.editor.get_p_params()
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
                start_t = self._current_event.get("start_time", 0)
                end_t = self._current_event.get("end_time", 0)
                pass
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

            new_lines = build_static_lines(
                original_lines,
                self.editor.current_scale_data,
                p_params,
                start_time=start_t,
                end_time=end_t,
                grain_seed=self.editor.get_seed(),
            )

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

        for channel, data in self.editor.current_scale_data.items():
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
