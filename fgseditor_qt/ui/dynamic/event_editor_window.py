from PySide6.QtWidgets import QDialog, QVBoxLayout, QMessageBox
from PySide6.QtCore import Qt

from fgseditor_qt.ui.static.single_editor import SingleEventEditor
from fgseditor_qt.ui.widgets.shortcuts import create_standard_menu
from fgseditor_qt.core.settings_manager import restore_window_geometry, save_window_geometry


class EventEditorUI(QDialog):
    def __init__(self, dynamic_timeline_ui, event_data):
        super().__init__(dynamic_timeline_ui)
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

        self.setWindowTitle(f"Edit FGS Event {event_data['event_idx'] + 1}")
        self.setMinimumSize(1100, 720)
        self.resize(1100, 720)
        restore_window_geometry(self, "geometry_event_editor")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        menu_bar = create_standard_menu(self)
        layout.setMenuBar(menu_bar)

        self.editor = SingleEventEditor(is_dynamic=True, parent=self)

        def _get_fps():
            try:
                fps = self.dynamic_timeline_ui._current_fps()
                fps_label = self.dynamic_timeline_ui.fps_combo.currentText()
                return fps, fps_label
            except Exception:
                return None, ""

        self.editor.fps_callback = _get_fps
        self.editor.load_event(self.event_data["event"], self.event_data["event_idx"])

        video_info = getattr(self.dynamic_timeline_ui.main_ui, "_video_info", None)
        if video_info:
            self.editor.set_video_info(video_info)

        all_events = self.dynamic_timeline_ui.events
        idx = self.event_data["event_idx"]
        min_t = 0
        max_t = 2**63 - 1
        if idx > 0:
            min_t = all_events[idx - 1]["end_time"]
        if idx < len(all_events) - 1:
            max_t = all_events[idx + 1]["start_time"]
        elif video_info:
            from fgseditor_qt.math.time_utils import video_info_to_ticks
            vid_ticks = video_info_to_ticks(video_info)
            if vid_ticks > 0:
                max_t = min(max_t, vid_ticks)

        self.editor.set_time_limits(min_t, max_t)

        self.editor.save_event_requested.connect(self.save_event)
        self.editor.cancel_requested.connect(self.close)
        self.editor.state_changed.connect(self._on_state_changed)

        layout.addWidget(self.editor)

    def _on_state_changed(self, dirty: bool):
        idx = self.event_data["event_idx"]
        event_id = self.event_data["event"].get("event_id", f"Idx {idx}")
        title = f"Event Editor - {event_id}"
        if dirty:
            title += " *"
        self.setWindowTitle(title)

    def _cleanup(self):
        save_window_geometry(self, "geometry_event_editor")
        if hasattr(self, "editor") and self.editor:
            self.editor.close_plotters()
        if hasattr(self, "dynamic_timeline_ui") and self.dynamic_timeline_ui:
            if getattr(self.dynamic_timeline_ui, "editor", None) is self:
                self.dynamic_timeline_ui.editor = None

    def accept(self):
        self._cleanup()
        super().accept()

    def reject(self):
        self._cleanup()
        super().reject()

    def closeEvent(self, event):
        if self.editor.is_dirty():
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "Save changes before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Save:
                if self.save_event():
                    event.accept()
                else:
                    event.ignore()
            elif reply == QMessageBox.Discard:
                self._cleanup()
                event.accept()
            else:
                event.ignore()
        else:
            self._cleanup()
            super().closeEvent(event)

    def save_event(self) -> bool:
        if self.editor.has_open_ar_windows():
            QMessageBox.warning(
                self,
                "AR Windows Open",
                "Close all AR coefficient windows before saving.",
                QMessageBox.Ok,
            )
            return False

        from fgseditor_qt.core.settings_manager import get_setting
        errors = self.editor.get_validation_errors()
        if errors and get_setting("show_unsafe_warnings", True):
            error_text = "\n".join(errors)
            reply = QMessageBox.warning(
                self,
                "Unsafe Preset",
                f"The current preset has stability or clipping issues:\n\n{error_text}\n\nSave anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return False

        self.dynamic_timeline_ui._push_undo()
        
        self.editor.apply_working_to_event()

        from fgseditor_qt.ui.dynamic.dynamic_ui import _process_timeline_event

        _, _, new_strength = _process_timeline_event((0, "", self.event_data["event"]))

        msg = f"Event {self.event_data['event_idx'] + 1} updated (amplitude: {new_strength:.2f})"
        if hasattr(self.dynamic_timeline_ui, "show_status_message"):
            self.dynamic_timeline_ui.show_status_message(msg, 3000)
        elif hasattr(self.dynamic_timeline_ui, "statusBar") and callable(self.dynamic_timeline_ui.statusBar):
            sb = self.dynamic_timeline_ui.statusBar()
            if sb:
                sb.showMessage(msg, 3000)

        self.dynamic_timeline_ui.build_timeline()
        self.dynamic_timeline_ui._update_ui_state()
        self.accept()
        return True
