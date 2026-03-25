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
)
from PySide6.QtCore import Qt

from .plotter import InteractiveFGSPlotter
from .shortcuts import create_standard_menu


class EventEditorUI(QDialog):
    def __init__(self, dynamic_timeline_ui, event_data):
        super().__init__()
        self.dynamic_timeline_ui = dynamic_timeline_ui
        self.event_data = event_data
        self.event_dict = event_data["event"]
        self.event_idx = event_data["event_idx"]

        self.setWindowTitle("Edit FGS Event")
        self.setMinimumSize(800, 600)
        self.setAttribute(Qt.WA_DeleteOnClose)

        self.original_scale_data = copy.deepcopy(self.event_dict["scale_data"])
        self.current_scale_data = copy.deepcopy(self.event_dict["scale_data"])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        menu_bar = create_standard_menu(self)
        layout.setMenuBar(menu_bar)

        top_frame = QFrame()
        top_frame.setObjectName("toolbar")
        controls_layout = QHBoxLayout(top_frame)

        controls_layout.addWidget(QLabel("Channel:"), stretch=0)

        self.channel_dropdown = QComboBox()
        self.channel_dropdown.addItems(["sY", "sCb", "sCr"])
        self.channel_dropdown.currentTextChanged.connect(self.on_channel_change)
        self.channel_dropdown.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        controls_layout.addWidget(self.channel_dropdown, stretch=0)

        controls_layout.addStretch()

        self.save_btn = QPushButton("Save Event")
        self.save_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.save_btn.clicked.connect(self.save_event)
        controls_layout.addWidget(self.save_btn, stretch=0)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.cancel_btn.clicked.connect(self.close)
        controls_layout.addWidget(self.cancel_btn, stretch=0)

        layout.addWidget(top_frame)

        self.plotter = InteractiveFGSPlotter()
        self.plotter.data_changed.connect(self.on_plotter_changed)
        layout.addWidget(self.plotter, stretch=1)

        self.plotter.set_data(self.current_scale_data)

    def on_channel_change(self, text):
        self.plotter.set_active_channel(text)

    def on_plotter_changed(self):
        self.current_scale_data = self.plotter.current_data

    def closeEvent(self, event):
        if self.current_scale_data != self.original_scale_data:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Do you want to save before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Save:
                self.save_event()
                self.plotter.close_plot()
                self.plotter = None
                event.accept()
            elif reply == QMessageBox.Cancel:
                event.ignore()
            else:
                self.plotter.close_plot()
                self.plotter = None
                event.accept()
        else:
            self.plotter.close_plot()
            self.plotter = None
            super().closeEvent(event)

    def save_event(self):
        self.dynamic_timeline_ui._push_undo()
        self.event_dict["scale_data"] = copy.deepcopy(self.current_scale_data)

        from .fgs_parser import avg_sy_strength

        new_strength = avg_sy_strength(self.event_dict)

        QMessageBox.information(
            self,
            "Event Updated",
            f"Event successfully updated.\nNew avg strength: {new_strength:.2f}",
        )

        self.dynamic_timeline_ui.build_timeline()
        self.accept()
