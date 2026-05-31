from PySide6.QtWidgets import QDialog, QVBoxLayout, QMessageBox
from PySide6.QtCore import Qt

from .single_editor import SingleEventEditor
from .shortcuts import create_standard_menu


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

        self.setWindowTitle(f"Edit FGS Event {event_data['event_idx'] + 1}")
        self.setMinimumSize(1100, 720)
        self.resize(1100, 720)
        self.setAttribute(Qt.WA_DeleteOnClose)

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

        all_events = self.dynamic_timeline_ui.events
        idx = self.event_data["event_idx"]
        min_t = 0
        max_t = 2**63 - 1
        if idx > 0:
            min_t = all_events[idx - 1]["end_time"]
        if idx < len(all_events) - 1:
            max_t = all_events[idx + 1]["start_time"]

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

    def closeEvent(self, event):
        if self.editor.is_dirty():
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
                self.editor.close_plotters()
                event.accept()
            else:
                event.ignore()
        else:
            self.editor.close_plotters()
            super().closeEvent(event)

    def save_event(self):
        from .settings_manager import get_setting
        errors = self.editor.get_validation_errors()
        if errors and get_setting("show_unsafe_warnings", True):
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
        
        self.editor.apply_working_to_event()
        
        self.dynamic_timeline_ui.build_timeline()

        from .dynamic_ui import _process_timeline_event

        _, _, new_strength = _process_timeline_event((0, "", self.event_data["event"]))

        QMessageBox.information(
            self,
            "Event Updated",
            f"Event {self.event_data['event_idx'] + 1} updated.\nNew effective amplitude: {new_strength:.2f}",
        )

        self.dynamic_timeline_ui.build_timeline()
        self.dynamic_timeline_ui._update_ui_state()
        self.accept()
