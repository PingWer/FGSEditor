from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QWidget,
    QMessageBox,
)
from PySide6.QtCore import Qt, QTimer, Signal

from fgseditor_qt.core import fgs_parser
from fgseditor_qt.ui.static.single_editor import SingleEventEditor
from fgseditor_qt.ui.widgets.shortcuts import create_standard_menu
from fgseditor_qt.core.settings_manager import restore_window_geometry, save_window_geometry


def _format_event_tags(indices: list[int], max_show: int = 8) -> str:
    if not indices:
        return ""
    if len(indices) <= max_show:
        return ", ".join(f"E{i + 1}" for i in indices)
    head_count = max(1, max_show - 2)
    head = ", ".join(f"E{i + 1}" for i in indices[:head_count])
    remaining = len(indices) - head_count - 1
    return f"{head}, ..., E{indices[-1] + 1} (+{remaining} more)"


class EventStatusOverlay(QWidget):
    enable_grain_clicked = Signal()
    cancel_clicked = Signal()
    jump_clicked = Signal(int)
    unlink_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("EventStatusOverlay")
        self.setStyleSheet("""
            QWidget#EventStatusOverlay {
                background-color: rgba(10, 12, 18, 0.88);
            }
            QFrame#StatusCard {
                background-color: #1a1c26;
                border: 1px solid #33384a;
                border-radius: 12px;
            }
            QLabel#TitleLabel {
                font-size: 16px;
                font-weight: bold;
                color: #ffffff;
            }
            QLabel#DescLabel {
                font-size: 12px;
                color: #b0b5c4;
                line-height: 1.4;
            }
            QPushButton {
                background-color: #2b3044;
                color: #ffffff;
                border: 1px solid #414764;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: bold;
                min-width: 90px;
            }
            QPushButton:hover {
                background-color: #3b425e;
                border-color: #555d82;
            }
            QPushButton#PrimaryBtn {
                background-color: #2563eb;
                border: 1px solid #3b82f6;
            }
            QPushButton#PrimaryBtn:hover {
                background-color: #1d4ed8;
            }
            QPushButton#ActionBtn {
                background-color: #0d9488;
                border: 1px solid #14b8a6;
            }
            QPushButton#ActionBtn:hover {
                background-color: #0f766e;
            }
            QPushButton#CancelBtn {
                background-color: #374151;
                border: 1px solid #4b5563;
            }
            QPushButton#CancelBtn:hover {
                background-color: #4b5563;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignCenter)

        self.card = QFrame()
        self.card.setObjectName("StatusCard")
        self.card.setFixedWidth(520)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(28, 24, 28, 24)
        card_layout.setSpacing(16)

        self.title_label = QLabel()
        self.title_label.setObjectName("TitleLabel")
        self.title_label.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(self.title_label)

        self.desc_label = QLabel()
        self.desc_label.setObjectName("DescLabel")
        self.desc_label.setWordWrap(True)
        self.desc_label.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(self.desc_label)

        self.btn_layout = QHBoxLayout()
        self.btn_layout.setSpacing(12)
        self.btn_layout.setAlignment(Qt.AlignCenter)
        card_layout.addLayout(self.btn_layout)

        main_layout.addWidget(self.card)
        self.master_idx: int | None = None

    def show_disabled_mode(self, downstream_linked: list[int] | None = None):
        self._clear_buttons()
        self.title_label.setText("⚠ Film Grain Disabled")
        self.title_label.setStyleSheet("color: #f87171;")
        desc = (
            "Film grain synthesis is currently disabled for this event (apply_grain = 0).\n"
            "All settings, curves, and parameters are locked.\n\n"
            "Click 'Enable Grain' to activate film grain and edit parameters,\n"
            "or 'Cancel' to return to the timeline."
        )
        if downstream_linked:
            tags = _format_event_tags(downstream_linked)
            desc += (
                f"\n\nNote: Enabling grain on this event will also make downstream "
                f"linked event(s) ({tags}) inherit from this event."
            )
        self.desc_label.setText(desc)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("CancelBtn")
        cancel_btn.clicked.connect(self.cancel_clicked.emit)

        enable_btn = QPushButton("Enable Grain")
        enable_btn.setObjectName("PrimaryBtn")
        enable_btn.clicked.connect(self.enable_grain_clicked.emit)

        self.btn_layout.addWidget(cancel_btn)
        self.btn_layout.addWidget(enable_btn)

    def show_linked_mode(self, master_idx: int | None, downstream_linked: list[int] | None = None):
        self._clear_buttons()
        self.master_idx = master_idx
        self.title_label.setText("🔗 Linked Event Parameters")
        self.title_label.setStyleSheet("color: #60a5fa;")

        if master_idx is not None:
            desc = (
                f"This event's values are linked to Event E{master_idx + 1} (update_parameters = 0).\n"
                "All settings, curves, and parameters are locked to the source event.\n\n"
                f"Press 'Jump to Event E{master_idx + 1}' to navigate to and edit the master event,\n"
                "or 'Unlink Event' to decouple this event and edit it independently."
            )
        else:
            desc = (
                "This event has update_parameters = 0, but no preceding active master event defines its parameters.\n"
                "All settings are locked.\n\n"
                "Press 'Unlink Event' to decouple this event and initialize parameters independently."
            )
        if downstream_linked:
            tags = _format_event_tags(downstream_linked)
            desc += (
                f"\n\nNote: Unlinking this event will also make downstream "
                f"linked event(s) ({tags}) inherit from this event."
            )
        self.desc_label.setText(desc)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("CancelBtn")
        cancel_btn.clicked.connect(self.cancel_clicked.emit)
        self.btn_layout.addWidget(cancel_btn)

        if master_idx is not None:
            jump_btn = QPushButton(f"Jump to Event E{master_idx + 1}")
            jump_btn.setObjectName("ActionBtn")
            jump_btn.clicked.connect(lambda: self.jump_clicked.emit(master_idx))
            self.btn_layout.addWidget(jump_btn)

        unlink_btn = QPushButton("Unlink Event")
        unlink_btn.setObjectName("PrimaryBtn")
        unlink_btn.clicked.connect(self.unlink_clicked.emit)
        self.btn_layout.addWidget(unlink_btn)

    def _clear_buttons(self):
        while self.btn_layout.count():
            item = self.btn_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()


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
        orig_ev = event_data["event"]
        self._orig_extra_params = list(orig_ev.get("extra_params") or ["1", "7391", "1"])
        self._orig_e_line = orig_ev.get(
            "e_line",
            f"E {orig_ev.get('start_time', 0)} {orig_ev.get('end_time', 0)} {' '.join(self._orig_extra_params)}\n",
        )

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

        self.master_banner = QFrame()
        self.master_banner.setObjectName("MasterLinkBanner")
        self.master_banner.setStyleSheet(
            "QFrame#MasterLinkBanner { background-color: #162436; border-bottom: 1px solid #2b4c70; }"
        )
        banner_layout = QHBoxLayout(self.master_banner)
        banner_layout.setContentsMargins(0, 0, 0, 0)
        self.master_banner_label = QLabel()
        self.master_banner_label.setWordWrap(True)
        self.master_banner_label.setStyleSheet(
            "color: #93c5fd; font-size: 12px; font-weight: bold; padding: 6px 12px;"
        )
        banner_layout.addWidget(self.master_banner_label)
        self.master_banner.hide()
        layout.addWidget(self.master_banner)

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

        # Status overlay for disabled or linked events
        self.overlay = EventStatusOverlay(self)
        self.overlay.enable_grain_clicked.connect(self._on_overlay_enable_grain)
        self.overlay.cancel_clicked.connect(self.close)
        self.overlay.jump_clicked.connect(self._on_overlay_jump)
        self.overlay.unlink_clicked.connect(self._on_overlay_unlink)
        self._check_status_overlay()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "overlay") and self.overlay:
            self.overlay.setGeometry(self.rect())

    def _check_status_overlay(self):
        ev = self.event_data["event"]
        idx = self.event_data["event_idx"]
        all_events = self.dynamic_timeline_ui.events
        downstream_linked = fgs_parser.find_linked_event_indices(
            all_events, idx, require_active_master=False
        )
        extra = list(ev.get("extra_params") or ["1", "7391", "1"])
        try:
            ag = int(extra[0]) if len(extra) > 0 else 1
            up = int(extra[2]) if len(extra) > 2 else 1
        except (ValueError, TypeError):
            ag, up = 1, 1

        if ag == 0:
            self.master_banner.hide()
            self.overlay.show_disabled_mode(downstream_linked=downstream_linked)
            self.overlay.setGeometry(self.rect())
            self.overlay.show()
            self.overlay.raise_()
            self.editor.setEnabled(False)
        elif up == 0:
            self.master_banner.hide()
            master_idx = fgs_parser.find_master_event_idx(all_events, idx)
            self.overlay.show_linked_mode(master_idx, downstream_linked=downstream_linked)
            self.overlay.setGeometry(self.rect())
            self.overlay.show()
            self.overlay.raise_()
            self.editor.setEnabled(False)
        else:
            self.overlay.hide()
            self.editor.setEnabled(True)
            if downstream_linked:
                tags = _format_event_tags(downstream_linked)
                self.master_banner_label.setText(
                    f"Master Event (E{idx + 1}) — Saving changes will automatically propagate "
                    f"to linked event(s): {tags} (update_parameters = 0)."
                )
                self.master_banner.show()
            else:
                self.master_banner.hide()

    def _on_overlay_enable_grain(self):
        ev = self.event_data["event"]
        extra = list(ev.get("extra_params") or ["1", "7391", "1"])
        if len(extra) < 3:
            defaults = ["1", "7391", "1"]
            extra.extend(defaults[len(extra) : 3])
        extra[0] = "1"
        extra[2] = "1"
        ev["extra_params"] = list(extra)
        ev["e_line"] = f"E {ev['start_time']} {ev['end_time']} {' '.join(extra)}\n"
        if hasattr(self.editor, "_working") and self.editor._working:
            self.editor._working["extra_params"] = list(extra)
            self.editor._working["e_line"] = ev["e_line"]

        self.editor._has_sanitization_changes = True
        self.editor._update_ui_state()
        self._check_status_overlay()

    def _on_overlay_unlink(self):
        ev = self.event_data["event"]
        extra = list(ev.get("extra_params") or ["1", "7391", "1"])
        if len(extra) < 3:
            defaults = ["1", "7391", "1"]
            extra.extend(defaults[len(extra) : 3])
        extra[2] = "1"
        ev["extra_params"] = list(extra)
        ev["e_line"] = f"E {ev['start_time']} {ev['end_time']} {' '.join(extra)}\n"
        if hasattr(self.editor, "_working") and self.editor._working:
            self.editor._working["extra_params"] = list(extra)
            self.editor._working["e_line"] = ev["e_line"]

        self.editor._has_sanitization_changes = True
        self.editor._update_ui_state()
        self._check_status_overlay()

    def _on_overlay_jump(self, master_idx: int):
        dyn_ui = self.dynamic_timeline_ui
        self._cleanup()
        self.accept()
        QTimer.singleShot(50, lambda: dyn_ui.open_editor(master_idx))

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

    def _restore_orig_extra_params(self):
        if hasattr(self, "event_data") and self.event_data and "event" in self.event_data:
            ev = self.event_data["event"]
            if hasattr(self, "_orig_extra_params"):
                ev["extra_params"] = list(self._orig_extra_params)
            if hasattr(self, "_orig_e_line"):
                ev["e_line"] = self._orig_e_line

    def accept(self):
        self._cleanup()
        super().accept()

    def reject(self):
        self._restore_orig_extra_params()
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
                self._restore_orig_extra_params()
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

        self._restore_orig_extra_params()
        self.dynamic_timeline_ui._push_undo()

        self.editor.apply_working_to_event()

        linked = fgs_parser.find_linked_event_indices(
            self.dynamic_timeline_ui.events, self.event_data["event_idx"]
        )

        from fgseditor_qt.ui.dynamic.dynamic_ui import _process_timeline_event

        _, _, new_strength = _process_timeline_event((0, "", self.event_data["event"]))

        msg = f"Event {self.event_data['event_idx'] + 1} updated (amplitude: {new_strength:.2f})"
        if linked:
            msg += f" — propagated to {_format_event_tags(linked)}"
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
