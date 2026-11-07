from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QButtonGroup, QLabel
from PySide6.QtCore import Signal, Qt


class SettingsTabsBar(QWidget):
    tab_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsTabsBar")
        self.setStyleSheet("""
            #settingsTabsBar {
                background: #1e1e30;
                border-bottom: 2px solid #333355;
            }
            QPushButton {
                background: transparent;
                color: #aaaaaa;
                border: none;
                font-size: 12px;
                font-weight: bold;
                padding: 6px 16px;
                border-bottom: 2px solid transparent;
            }
            QPushButton:hover {
                color: #ffffff;
                background: #252540;
            }
            QPushButton:checked {
                color: #4da6ff;
                border-bottom: 2px solid #4da6ff;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)
        self.btn_group.idClicked.connect(self._on_btn_clicked)

        tabs = ["General", "Grain Size", "Photon Noise", "Templates", "Time", "All"]

        for i, text in enumerate(tabs):
            btn = QPushButton(text)
            btn.setCheckable(True)
            self.btn_group.addButton(btn, i)
            layout.addWidget(btn)

            if i == 5:
                btn.setChecked(True)

        layout.addStretch()

        self.ar_label = QLabel("AR Value:")
        self.ar_label.setStyleSheet(
            "color: #aaaaaa; font-size: 12px; font-weight: bold; margin-left: 10px; margin-right: 5px; border: none; background: transparent;"
        )
        layout.addWidget(self.ar_label)

        self.ar_buttons = {}
        for ch in ["Y", "Cb", "Cr"]:
            btn = QPushButton(ch)
            btn.setFixedWidth(36)
            btn.setCursor(
                Qt.PointingHandCursor
                if hasattr(Qt, "PointingHandCursor")
                else Qt.ArrowCursor
            )
            btn.setStyleSheet("""
                QPushButton {
                    background: #2d2d44;
                    color: #4da6ff;
                    border: 1px solid #333355;
                    border-radius: 3px;
                    font-size: 11px;
                    font-weight: bold;
                    padding: 3px 0;
                    margin-right: 5px;
                }
                QPushButton:hover {
                    background: #3d3d5c;
                    color: #ffffff;
                }
                QPushButton:pressed {
                    background: #1d1d2c;
                }
            """)
            layout.addWidget(btn)
            self.ar_buttons[ch] = btn

    def _on_btn_clicked(self, id):
        self.tab_changed.emit(id)
