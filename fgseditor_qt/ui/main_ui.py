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
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QRectF, QByteArray
from PySide6.QtGui import QPainter, QColor, QPen, QBrush
from PySide6.QtSvg import QSvgRenderer

from fgseditor_qt.core.app_paths import get_base_dir
from fgseditor_qt.core.settings_manager import (
    get_setting,
    get_dialog_dir,
    update_dialog_dir,
    restore_window_geometry,
    save_window_geometry,
)
from fgseditor_qt.ui.widgets.shortcuts import create_standard_menu, show_credits, open_github, show_notice
from fgseditor_qt.ui.static.single_editor import SingleEventEditor

from fgseditor_qt.core import fgs_parser


class LoadingSpinner(QWidget):
    def __init__(self, parent=None, size=40, color=QColor("#2a82da")):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.color = color
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.rotate_spinner)
        self.timer.start(80)
        self.angle_offset = 0

    def rotate_spinner(self):
        self.angle_offset = (self.angle_offset + 1) % 8
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        height = self.height()
        painter.translate(width / 2.0, height / 2.0)

        for i in range(8):
            diff = (i - self.angle_offset) % 8
            opacity = int(255 * (1.0 - diff * 0.1))
            tick_color = QColor(self.color)
            tick_color.setAlpha(max(40, opacity))

            painter.save()
            painter.rotate(i * 45)

            pen = QPen(tick_color)
            pen.setWidth(4)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)

            painter.drawLine(0, -10, 0, -18)
            painter.restore()


class LoadingDialog(QDialog):
    def __init__(self, parent=None, message="Loading video stream info..."):
        super().__init__(parent)
        self.setWindowModality(Qt.WindowModal)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.container = QWidget(self)
        self.container.setObjectName("container")
        self.container.setStyleSheet("""
            QWidget#container {
                background-color: #1a1a2e;
                border: 2px solid #333355;
                border-radius: 12px;
            }
            QLabel {
                color: #dddddd;
                font-size: 13px;
                font-weight: bold;
            }
        """)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignCenter)

        self.spinner = LoadingSpinner(self, size=50)
        layout.addWidget(self.spinner, alignment=Qt.AlignCenter)

        self.label = QLabel(message, self)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label, alignment=Qt.AlignCenter)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.container)

        self.setFixedSize(320, 180)

    def showEvent(self, event):
        super().showEvent(event)
        if self.parent():
            parent_geo = self.parent().geometry()
            self.move(
                parent_geo.x() + (parent_geo.width() - self.width()) // 2,
                parent_geo.y() + (parent_geo.height() - self.height()) // 2,
            )


class VideoLoadWorker(QThread):
    finished_data = Signal(bool, object, str)

    def __init__(self, filepath):
        super().__init__()
        self.filepath = filepath

    def run(self):
        from fgseditor_qt.tools.video_probe import probe_video
        from fgseditor_qt.tools import fgs_tools
        import os

        try:
            info = probe_video(self.filepath)
        except Exception as exc:
            self.finished_data.emit(False, exc, "")
            return

        codec = info.get("codec", "").lower()
        is_av1 = codec == "av1"

        fgs_path = ""
        if is_av1:
            video_base = os.path.splitext(self.filepath)[0]
            candidate_fgs = f"{video_base}_fgs.txt"
            try:
                has_fgs = fgs_tools.inspect_fgs(self.filepath, candidate_fgs)
                if has_fgs and os.path.isfile(candidate_fgs):
                    fgs_path = candidate_fgs
            except Exception:
                pass

        self.finished_data.emit(True, info, fgs_path)


class SettingsButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsButton")
        self.setFixedSize(42, 42)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Settings")
        self._is_hovered = False
        self._is_pressed = False

        self._renderers = {
            "normal": QSvgRenderer(QByteArray(self._build_svg("#9aa0b4").encode("utf-8"))),
            "hover": QSvgRenderer(QByteArray(self._build_svg("#ffffff").encode("utf-8"))),
            "pressed": QSvgRenderer(QByteArray(self._build_svg("#88c0ff").encode("utf-8"))),
        }

    @staticmethod
    def _build_svg(color: str) -> str:
        return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>
  <circle cx="12" cy="12" r="3"/>
</svg>"""

    def enterEvent(self, event):
        self._is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._is_hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._is_pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._is_pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self._is_pressed:
            bg_color = QColor("#181920")
            border_color = QColor("#2a75d3")
            renderer = self._renderers["pressed"]
        elif self._is_hovered:
            bg_color = QColor("#282a36")
            border_color = QColor("#4da6ff")
            renderer = self._renderers["hover"]
        else:
            bg_color = QColor("#1f2029")
            border_color = QColor("#353849")
            renderer = self._renderers["normal"]

        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(border_color, 1.2))
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(rect, 10, 10)

        icon_size = 20.0
        icon_rect = QRectF(
            (self.width() - icon_size) / 2.0,
            (self.height() - icon_size) / 2.0,
            icon_size,
            icon_size,
        )
        renderer.render(painter, icon_rect)
        painter.end()


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

        self.opt_btn = QPushButton("Optimize FGS")
        self.opt_btn.setObjectName("bigButton")
        self.opt_btn.setFixedSize(320, 80)
        self.opt_btn.clicked.connect(self.main_ui.open_optimizer_dialog)
        layout.addWidget(self.opt_btn, alignment=Qt.AlignCenter)

        self.create_btn = QPushButton("Create FGS")

        self.create_btn.setObjectName("bigButton")
        self.create_btn.setFixedSize(320, 80)

        create_menu = QMenu(self.create_btn)
        create_menu.addAction("Manual Creation").triggered.connect(
            self.main_ui.create_static_fgs
        )
        create_menu.addAction("Automatic Creation").triggered.connect(
            self.main_ui.open_auto_create_dialog
        )
        self.create_btn.setMenu(create_menu)

        layout.addWidget(self.create_btn, alignment=Qt.AlignCenter)

        drop_label = QLabel(
            "Drag and drop an FGS table (.txt, .tbl) or video file here"
        )
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

        self.settings_btn = SettingsButton(self)
        self.settings_btn.clicked.connect(self.main_ui.open_settings)

    def _update_settings_btn_pos(self):
        if hasattr(self, "settings_btn"):
            btn_w = self.settings_btn.width()
            btn_h = self.settings_btn.height()
            margin = 24
            self.settings_btn.move(
                max(0, self.width() - btn_w - margin),
                max(0, self.height() - btn_h - margin),
            )
            self.settings_btn.raise_()

    def showEvent(self, event):
        super().showEvent(event)
        self._update_settings_btn_pos()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_settings_btn_pos()

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
            event.acceptProposedAction()
            ext = os.path.splitext(filepath)[1].lower()
            if ext in (".txt", ".tbl"):
                QTimer.singleShot(0, lambda p=filepath: self.main_ui.load_file_from_path(p))
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
            ):
                QTimer.singleShot(0, lambda p=filepath: self.main_ui.load_video(p))


class MainUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FGSEditor")
        self.setMinimumSize(1000, 650)
        if not restore_window_geometry(self, "geometry_main_window"):
            self.resize(1200, 800)
        self.setAcceptDrops(True)

        self.filepath = None
        self._current_event = None

        self._video_path: str | None = None
        self._video_info: dict | None = None
        self.dynamic_ui = None

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

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self._do_autosave)

        interval_min = get_setting("autosave_interval_minutes", 5)
        if interval_min > 0:
            self.autosave_timer.start(interval_min * 60000)

    def open_settings(self):
        from fgseditor_qt.ui.dialogs.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.exec()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            filepath = urls[0].toLocalFile()
            event.acceptProposedAction()
            ext = os.path.splitext(filepath)[1].lower()
            if ext in (".txt", ".tbl"):
                QTimer.singleShot(0, lambda p=filepath: self.load_file_from_path(p))
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
            ):
                QTimer.singleShot(0, lambda p=filepath: self.load_video(p))

    def _do_autosave(self):
        if not self.editor.is_dirty() or not self._current_event:
            return

        import datetime
        from fgseditor_qt.core.fgs_save import build_static_lines

        backup_dir = os.path.join(get_base_dir(), "backup")
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        if self.filepath and os.path.basename(self.filepath) != "Untitled":
            base_name = os.path.splitext(os.path.basename(self.filepath))[0]
        else:
            base_name = "Untitled"

        backup_filename = f"{base_name}_{timestamp}_static.txt"
        backup_path = os.path.join(backup_dir, backup_filename)

        try:
            working = self.editor.get_working_event()
            event_raw_lines = working.get("raw_lines") or []
            start_t = working.get("start_time", 0)
            end_t = working.get("end_time", 0)
            p_params = working.get("p_params") or self.editor.get_p_params()
            grain_seed = self.editor.get_seed()

            lines = build_static_lines(
                event_raw_lines,
                working.get("scale_data") or self.editor.current_scale_data,
                p_params,
                start_time=start_t,
                end_time=end_t,
                grain_seed=grain_seed,
            )
            with open(backup_path, "w", encoding="utf-8", newline="\n") as f:
                f.writelines(lines)
        except Exception:
            pass

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
        if hasattr(self, "autosave_timer") and self.autosave_timer.isActive():
            self.autosave_timer.stop()

        is_editing = (
            self.stacked_widget.currentWidget() != self.welcome_screen
            and (self.filepath is not None or self._current_event is not None)
        )
        if is_editing and self.editor.is_dirty():
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "Save changes before exiting?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Save:
                if not self.save_file():
                    event.ignore()
                    return
                self.editor.close_plotters()
                save_window_geometry(self, "geometry_main_window")
                event.accept()
            elif reply == QMessageBox.Discard:
                self.editor.close_plotters()
                save_window_geometry(self, "geometry_main_window")
                event.accept()
            elif reply == QMessageBox.Cancel:
                event.ignore()
                return
        else:
            self.editor.close_plotters()
            save_window_geometry(self, "geometry_main_window")
            event.accept()

    def close_fgs(self):
        if self.editor.is_dirty():
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "Save changes before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Save:
                if not self.save_file():
                    return
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
        if hasattr(self, "dynamic_ui") and self.dynamic_ui is not None:
            self.dynamic_ui.close()
            self.dynamic_ui = None
        self.stacked_widget.setCurrentIndex(0)
        self.setWindowTitle("FGSEditor")

    def load_file(self):
        if self.editor.is_dirty():
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "Save changes before opening another file?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Save:
                if not self.save_file():
                    return
            elif reply == QMessageBox.Cancel:
                return

        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select FGS file",
            get_dialog_dir("last_fgs_dir"),
            "FGS Files (*.txt *.tbl);;All Files (*)",
        )
        if not filename:
            return
        update_dialog_dir("last_fgs_dir", filename)
        self.load_file_from_path(filename)

    def load_video_dialog(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Supported Video",
            get_dialog_dir("last_video_dir"),
            "Video Files (*.mkv *.ivf *.hevc *.avi *.mov *.webm *.ts *.flv);;All Files (*)",
        )
        if not filename:
            return
        update_dialog_dir("last_video_dir", filename)
        self.load_video(filename)

    def open_optimizer_dialog(self, initial_fgs_path: str | None = None):
        from fgseditor_qt.ui.dialogs.fgs_optimizer_dialog import FgsOptimizerDialog

        fgs_p = initial_fgs_path or self.filepath
        video_p = self._video_path
        dlg = FgsOptimizerDialog(self, initial_fgs_path=fgs_p, initial_video_path=video_p)
        dlg.fgs_loaded.connect(self.load_file_from_path)
        dlg.exec()

    def open_auto_create_dialog(self, initial_video_path: str | None = None):
        from fgseditor_qt.ui.dialogs.fgs_auto_create_dialog import FgsAutoCreateDialog

        video_p = initial_video_path or self._video_path or ""
        dlg = FgsAutoCreateDialog(self, initial_video_path=video_p)
        dlg.fgs_loaded.connect(self.load_file_from_path)
        dlg.exec()


    def load_video(self, filepath):
        self._load_dialog = LoadingDialog(
            self, f"Loading {os.path.basename(filepath)}..."
        )
        self._load_worker = VideoLoadWorker(filepath)

        def _on_load_finished(success, info_or_exc, fgs_path):
            self._load_dialog.accept()
            if not success:
                exc = info_or_exc

                if isinstance(exc, FileNotFoundError):
                    QMessageBox.critical(self, "ffprobe Not Found", str(exc))
                else:
                    QMessageBox.critical(self, "Video Error", str(exc))
                return

            info = info_or_exc
            self._video_path = filepath
            self._video_info = info

            has_fgs = bool(fgs_path)

            is_active_editor = (
                self.stacked_widget.currentIndex() == 1
                or (hasattr(self, "dynamic_ui") and self.dynamic_ui is not None and self.dynamic_ui.isVisible())
            )

            if has_fgs:
                reply = QMessageBox.question(
                    self,
                    "FGS Found",
                    "Video contains film grain metadata.\n\n"
                    "Edit existing grain table?",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                )
                if reply == QMessageBox.Cancel:
                    return
                if reply == QMessageBox.Yes:
                    self.load_file_from_path(fgs_path)
                    self._setup_video_context(filepath, info)
                    return
                elif is_active_editor:
                    self._setup_video_context(filepath, info)
                    return

            if is_active_editor:
                self._setup_video_context(filepath, info)
                return

            choice_dialog = QDialog(self)
            choice_dialog.setWindowTitle("Create Film Grain Synthesis")
            choice_dialog.setMinimumWidth(500)
            _cd_layout = QVBoxLayout(choice_dialog)
            _cd_layout.setSpacing(14)

            _cd_title = QLabel(
                "<b>No film grain metadata found in video.</b>"
                if not has_fgs
                else "<b>Create grain table:</b>"
            )
            _cd_title.setTextFormat(Qt.RichText)
            _cd_layout.addWidget(_cd_title)

            _cd_static_desc = QLabel(
                "<b>Static FGS</b> — Single grain preset applied uniformly across the video duration."
            )
            _cd_static_desc.setWordWrap(True)
            _cd_layout.addWidget(_cd_static_desc)

            _cd_dynamic_desc = QLabel(
                "<b>Dynamic FGS</b> — Timeline editor with multiple grain events and keyframe intervals."
            )
            _cd_dynamic_desc.setWordWrap(True)
            _cd_layout.addWidget(_cd_dynamic_desc)

            _cd_auto_desc = QLabel(
                "<b>Automatic</b> — Extract and optimize grain automatically from video using av-denoise."
            )
            _cd_auto_desc.setWordWrap(True)
            _cd_layout.addWidget(_cd_auto_desc)

            _cd_btn_layout = QHBoxLayout()
            _cd_static_btn = QPushButton("Static FGS")
            _cd_static_btn.setMinimumWidth(100)
            _cd_dynamic_btn = QPushButton("Dynamic FGS")
            _cd_dynamic_btn.setMinimumWidth(100)
            _cd_auto_btn = QPushButton("Automatic")
            _cd_auto_btn.setObjectName("primaryBtn")
            _cd_auto_btn.setMinimumWidth(100)
            _cd_cancel_btn = QPushButton("Cancel")
            _cd_cancel_btn.setMinimumWidth(80)

            _cd_btn_layout.addWidget(_cd_static_btn)
            _cd_btn_layout.addWidget(_cd_dynamic_btn)
            _cd_btn_layout.addWidget(_cd_auto_btn)
            _cd_btn_layout.addWidget(_cd_cancel_btn)
            _cd_layout.addLayout(_cd_btn_layout)

            _cd_choice = [None]

            def _pick_static():
                _cd_choice[0] = "static"
                choice_dialog.accept()

            def _pick_dynamic():
                _cd_choice[0] = "dynamic"
                choice_dialog.accept()

            def _pick_auto():
                _cd_choice[0] = "auto"
                choice_dialog.accept()

            _cd_static_btn.clicked.connect(_pick_static)
            _cd_dynamic_btn.clicked.connect(_pick_dynamic)
            _cd_auto_btn.clicked.connect(_pick_auto)
            _cd_cancel_btn.clicked.connect(choice_dialog.reject)

            if choice_dialog.exec() != QDialog.Accepted or not _cd_choice[0]:
                return

            choice = _cd_choice[0]
            self._setup_video_context(filepath, info)

            if choice == "auto":
                self.open_auto_create_dialog(initial_video_path=filepath)
            elif choice == "dynamic":
                from fgseditor_qt.core.fgs_templates import get_system_dir
                from fgseditor_qt.math.time_utils import video_info_to_ticks
                from fgseditor_qt.ui.dynamic.dynamic_ui import DynamicTimelineUI

                default_path = os.path.join(get_system_dir(), "default.txt")
                if os.path.isfile(default_path):
                    with open(default_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    h_lines, evs = fgs_parser.parse_fgs_events(content, video_info=info)
                else:
                    h_lines = ["filmgrn1\n"]
                    evs = []

                vid_ticks = video_info_to_ticks(info)
                if vid_ticks > 0 and evs:
                    evs[0]["start_time"] = 0
                    evs[0]["end_time"] = vid_ticks
                    params_str = " ".join(evs[0].get("extra_params", ["1", "7391", "1"]))
                    evs[0]["e_line"] = f"E 0 {vid_ticks} {params_str}\n"

                self.dynamic_ui = DynamicTimelineUI(
                    self,
                    {
                        "header_lines": h_lines,
                        "events": evs,
                        "filepath": None,
                        "is_temp": True,
                    },
                )
                self.hide()
                self.dynamic_ui.show()
            else:
                self.create_static_fgs()
                self._setup_video_context(filepath, info)

        self._load_worker.finished_data.connect(_on_load_finished)
        self._load_worker.start()
        self._load_dialog.exec()

    def _setup_video_context(self, video_path: str, info: dict):
        self._video_path = video_path
        self._video_info = info
        self.editor.set_video_info(info)

        if self._current_event and info:
            from fgseditor_qt.math.time_utils import video_info_to_ticks
            vid_ticks = video_info_to_ticks(info)

            if vid_ticks > 0 and self._current_event.get("end_time", 0) > vid_ticks:
                self._current_event["end_time"] = vid_ticks
                self.editor.set_times(self._current_event.get("start_time", 0), vid_ticks)

        if hasattr(self, "dynamic_ui") and self.dynamic_ui is not None:
            self.dynamic_ui._clamp_last_event_to_video_duration()
            self.dynamic_ui.build_timeline()

        from fgseditor_qt.tools import fgs_tools

        codec = info.get("codec", "").lower()
        ext = os.path.splitext(video_path)[1].lower()
        is_av1 = codec == "av1"
        is_supported_container = ext in (".mkv", ".ivf")
        preferred = fgs_tools.get_preferred_tool()

        enabled = False
        tooltip = ""
        if not is_av1:
            tooltip = f"Save & Apply is only available for AV1 videos (current: {codec.upper()})."
        elif not is_supported_container:
            tooltip = f"Save & Apply is only supported for .mkv and .ivf containers (current: {ext})."
        elif preferred is None:
            enabled = True
            tooltip = "No FGS tool found.\nPlease check Settings."
        else:
            enabled = True
            tooltip = f"Save FGS and apply grain to video ({preferred})."

        self.editor.set_save_apply_enabled(enabled, tooltip)
        if hasattr(self, "dynamic_ui") and self.dynamic_ui is not None:
            self.dynamic_ui.set_save_apply_enabled(enabled, tooltip)

        fname = os.path.basename(video_path)
        self.editor.set_file_label(f"Editing FGS for: {fname}")
        if hasattr(self, "dynamic_ui") and self.dynamic_ui is not None:
            self.dynamic_ui.set_file_label(f"File: {self.dynamic_ui.filepath} | Video: {fname}")
        self._on_state_changed(self.editor.is_dirty())

    def load_file_from_path(self, filepath):
        if hasattr(self, "dynamic_ui") and self.dynamic_ui is not None and self.dynamic_ui.isVisible():
            if self.dynamic_ui.is_dirty() and filepath != self.dynamic_ui.filepath:
                reply = QMessageBox.question(
                    self,
                    "Unsaved Changes",
                    "Save timeline changes before loading new file?",
                    QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                    QMessageBox.Save,
                )
                if reply == QMessageBox.Save:
                    if not self.dynamic_ui.save_fgs():
                        return
                elif reply == QMessageBox.Cancel:
                    return
        elif self.editor.is_dirty() and filepath != self.filepath:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "Save changes before loading new file?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Save:
                if not self.save_file():
                    return
            elif reply == QMessageBox.Cancel:
                return

        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            header_lines, events, warnings = fgs_parser.parse_fgs_events(
                content, return_warnings=True, video_info=self._video_info
            )
            if warnings:
                from fgseditor_qt.ui.dialogs.fgs_warning_dialog import NonStandardFgsDialog

                dlg = NonStandardFgsDialog(self, warnings)
                dlg.exec()
        except Exception as ex:
            QMessageBox.critical(self, "Error", f"An error occurred:\n{str(ex)}")
            return

        from fgseditor_qt.core.app_paths import is_temp_filepath
        is_temp = is_temp_filepath(filepath)

        self.editor.close_plotters()
        self.filepath = filepath
        self._is_temp = is_temp
        if is_temp:
            self.editor.set_file_label("Editing: Unsaved New FGS")
        else:
            self.editor.set_file_label(f"Editing: {self.filepath}")

        if fgs_parser.is_dynamic(events):
            from fgseditor_qt.ui.dynamic.dynamic_ui import DynamicTimelineUI

            self.dynamic_ui = DynamicTimelineUI(
                self,
                {
                    "header_lines": header_lines,
                    "events": events,
                    "filepath": self.filepath,
                    "is_temp": is_temp,
                },
            )
            if warnings:
                self.dynamic_ui.set_has_sanitization_changes(True)
            self.hide()
            self.dynamic_ui.show()
        else:
            event = events[0] if events else {}
            self._current_event = event
            self.editor.load_event(event)
            self.editor._is_temp = is_temp
            if warnings:
                self.editor.set_has_sanitization_changes(True)
            self.stacked_widget.setCurrentIndex(1)
            self._on_state_changed(self.editor.is_dirty())

        if self._video_path and self._video_info:
            self._setup_video_context(self._video_path, self._video_info)

    def create_static_fgs(self):
        if self.editor.is_dirty():
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "Save changes before creating a new file?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Save:
                if not self.save_file():
                    return
            elif reply == QMessageBox.Cancel:
                return

        from fgseditor_qt.core.fgs_templates import get_system_dir

        default_path = os.path.join(get_system_dir(), "default.txt")
        if not os.path.isfile(default_path):
            QMessageBox.warning(
                self, "Missing Default", "Could not find Templates/system/default.txt"
            )
            return

        self.load_file_from_path(default_path)
        self.filepath = None
        self._is_temp = True
        self.editor._is_temp = True
        self.editor.set_file_label("Editing: Unsaved New FGS")
        self._on_state_changed(True)

    def save_file(self):
        if self.editor.has_open_ar_windows():
            QMessageBox.warning(
                self,
                "AR Windows Open",
                "Close all AR coefficient windows before saving.",
                QMessageBox.Ok,
            )
            return False

        start_t, end_t = self.editor.get_event_time_bounds()
        if hasattr(self, "_video_info") and self._video_info:
            from fgseditor_qt.math.time_utils import video_info_to_ticks
            vid_ticks = video_info_to_ticks(self._video_info)
            if vid_ticks > 0 and end_t > vid_ticks:
                end_t = vid_ticks
                self.editor.set_times(start_t, end_t)

        if self._current_event:
            self._current_event["start_time"] = start_t
            self._current_event["end_time"] = end_t

        if not self.filepath:
            pass

        errors = self.editor.get_validation_errors()
        if errors:
            error_text = "\n".join(errors)
            reply = QMessageBox.warning(
                self,
                "Unsafe Preset",
                f"Preset has stability or clipping issues:\n\n{error_text}\n\nSave anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return False

        p_params = self.editor.get_p_params()
        working = self.editor.get_working_event()
        event_raw_lines = (
            working.get("raw_lines") if working else (
                self._current_event.get("raw_lines") if self._current_event else None
            )
        )
        from fgseditor_qt.core.app_paths import is_temp_filepath
        is_temp = getattr(self, "_is_temp", False) or not self.filepath or is_temp_filepath(self.filepath)

        default_name = "grain.tbl"
        if self._video_path:
            video_base = os.path.splitext(os.path.basename(self._video_path))[0]
            default_name = f"{video_base}.tbl"

        force_path = None if is_temp else self.filepath
        if self.filepath and not is_temp:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Save Options")
            msg_box.setText(
                f"File already exists:\n{os.path.basename(self.filepath)}\n\nOverwrite or save as a new file?"
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
        from fgseditor_qt.core.fgs_save import save_static_fgs

        saved_path = save_static_fgs(
            self,
            original_filepath=None if is_temp else self.filepath,
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
            self._is_temp = False
            self.editor._is_temp = False
            self.editor.apply_working_to_event()
            self.editor.set_file_label(f"Editing: {os.path.basename(self.filepath)}")
            self.editor.set_has_sanitization_changes(False)
            self._on_state_changed(False)
            return True
        self._on_state_changed(self.editor.is_dirty())
        return False

    def save_binary_file(self):
        from PySide6.QtWidgets import QMessageBox

        if hasattr(self, "_video_info") and self._video_info:
            codec = self._video_info.get("codec", "").lower()
            if codec and codec not in ("av1", "hevc"):
                reply = QMessageBox.warning(
                    self,
                    "Codec Warning",
                    f"Video codec '{codec.upper()}' may not support AFGS1 specification.\n\nContinue?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply == QMessageBox.No:
                    return

        from fgseditor_qt.core.app_paths import is_temp_filepath
        is_dirty = (
            self.editor.is_dirty()
            or not self.filepath
            or getattr(self, "_is_temp", False)
            or is_temp_filepath(self.filepath)
        )
        if is_dirty:
            reply = QMessageBox.question(
                self,
                "Save FGS Required",
                "The FGS table must be saved before exporting to binary AFGS1 payload.\n\nSave FGS table now?",
                QMessageBox.Save | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply != QMessageBox.Save:
                return
            if not self.save_file():
                return
            if self.editor.is_dirty() or not self.filepath or is_temp_filepath(self.filepath):
                return

        from PySide6.QtWidgets import QFileDialog, QMessageBox

        from fgseditor_qt.math.time_utils import DEFAULT_FPS_LABEL, fps_from_label
        default_fps = fps_from_label(get_setting("default_fps", DEFAULT_FPS_LABEL))
        if hasattr(self, "_video_info") and self._video_info:
            fps = self._video_info.get("fps", 0)
            if fps <= 0:
                fps = default_fps
            num_frames = self._video_info.get("num_frames") or 0
            if num_frames <= 0:
                dur_s = self._video_info.get("duration_s", 0)
                if fps > 0 and dur_s > 0:
                    num_frames = max(1, round(dur_s * fps))
                else:
                    num_frames = get_setting("fallback_export_frames", 150000)
        else:
            fps = default_fps
            start_t, end_t = self.editor.get_event_time_bounds()
            dur_s = (end_t - start_t) / 10000000.0
            if fps > 0 and dur_s > 0:
                num_frames = max(1, round(dur_s * fps))
            else:
                num_frames = get_setting("fallback_export_frames", 150000)

        if num_frames <= 0:
            QMessageBox.warning(
                self, "Invalid Duration", "Duration must be greater than 0."
            )
            return

        default_out = os.path.splitext(self.filepath)[0] + ".bin"

        from fgseditor_qt.ui.dialogs.fgs_warning_dialog import ask_static_dynamic_mode

        static_mode = ask_static_dynamic_mode(self, title="Binary Export Mode")
        if static_mode is None:
            return

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save AFGS1 Binary Payload",
            default_out,
            "Binary AFGS1 (*.bin)",
        )
        if not output_path:
            return

        from fgseditor_qt.core.binary_x265_FGS import parse_and_pack

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
        if self.editor.has_open_ar_windows():
            QMessageBox.warning(
                self,
                "AR Windows Open",
                "Close all AR coefficient windows before applying.",
                QMessageBox.Ok,
            )
            return

        if not self._video_path:
            video_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select Source AV1 Video (.mkv, .ivf)",
                get_dialog_dir("last_video_dir"),
                "AV1 Video (*.mkv *.ivf);;All Files (*)",
            )
            if not video_path:
                return
            update_dialog_dir("last_video_dir", video_path)
            self.load_video(video_path)
            if not self._video_path:
                return

        codec = self._video_info.get("codec", "").lower() if self._video_info else ""
        ext = os.path.splitext(self._video_path)[1].lower() if self._video_path else ""
        if codec != "av1" or ext not in (".mkv", ".ivf"):
            QMessageBox.critical(
                self,
                "Unsupported Video Format",
                "Save & Apply requires an AV1 video (.mkv or .ivf).\n\n"
                f"Current format: {codec.upper()} ({ext})",
            )
            return

        from fgseditor_qt.tools import fgs_tools

        tool_name, tool_path = fgs_tools.get_active_tool_path()
        if tool_path is None:
            QMessageBox.critical(
                self,
                "FGS Tool Not Found",
                "No FGS tool found.\n\nPlease check Settings.",
            )
            return

        start_t, end_t = self.editor.get_event_time_bounds()
        if hasattr(self, "_video_info") and self._video_info:
            from fgseditor_qt.math.time_utils import video_info_to_ticks
            vid_ticks = video_info_to_ticks(self._video_info)
            if vid_ticks > 0 and end_t > vid_ticks:
                end_t = vid_ticks
                self.editor.set_times(start_t, end_t)

        if self._current_event is not None:
            self._current_event["start_time"] = start_t
            self._current_event["end_time"] = end_t

        from fgseditor_qt.core.app_paths import is_temp_filepath
        is_dirty = (
            self.editor.is_dirty()
            or not self.filepath
            or getattr(self, "_is_temp", False)
            or is_temp_filepath(self.filepath)
        )
        if is_dirty:
            reply = QMessageBox.question(
                self,
                "Save FGS Required",
                "The FGS table must be saved before applying it to the video.\n\nSave FGS table now?",
                QMessageBox.Save | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply != QMessageBox.Save:
                return
            if not self.save_file():
                return
            if self.editor.is_dirty() or not self.filepath or is_temp_filepath(self.filepath):
                return

        errors = self.editor.get_validation_errors()
        if errors:
            error_text = "\n".join(errors)
            reply = QMessageBox.warning(
                self,
                "Unsafe Preset",
                f"Preset has stability or clipping issues:\n\n{error_text}\n\nContinue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return

        from fgseditor_qt.ui.dialogs.fgs_warning_dialog import ask_static_dynamic_mode

        static_mode = ask_static_dynamic_mode(self, title="Apply FGS Mode")
        if static_mode is None:
            return

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

        if os.path.abspath(output_path) == os.path.abspath(self._video_path):
            QMessageBox.warning(
                self,
                "Invalid Output Video",
                "The output video path cannot be the same as the source video.",
            )
            return

        from PySide6.QtWidgets import QProgressDialog, QApplication

        progress = QProgressDialog(
            "Applying film grain to video...",
            "Cancel",
            0,
            100,
            self,
        )
        progress.setWindowTitle("Applying FGS")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()

        def on_progress(pct: float, msg: str):
            progress.setValue(int(pct))
            progress.setLabelText(msg)
            QApplication.processEvents()

        def check_cancelled() -> bool:
            QApplication.processEvents()
            return progress.wasCanceled()

        success, msg = fgs_tools.apply_fgs(
            self._video_path,
            self.filepath,
            output_path,
            is_static=static_mode,
            progress_callback=on_progress,
            cancel_check=check_cancelled,
        )
        progress.close()

        if not success and msg == "Operation cancelled by user.":
            return

        if success:
            QMessageBox.information(
                self,
                "Success",
                f"Film grain applied successfully!\n\nOutput: {output_path}\nFGS applied: {self.filepath}",
            )
        else:
            QMessageBox.critical(
                self,
                "Apply Failed",
                f"Failed to apply film grain:\n\n{msg}\n\nFGS used: {self.filepath}",
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
