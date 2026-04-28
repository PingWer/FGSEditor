from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QButtonGroup
from PySide6.QtCore import Signal

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

        tabs = ["FGS Values", "Grain Size", "Photon Noise", "Templates", "Time", "All"]

        for i, text in enumerate(tabs):
            btn = QPushButton(text)
            btn.setCheckable(True)
            self.btn_group.addButton(btn, i)
            layout.addWidget(btn)

            if i == 5:  # Default select "All"
                btn.setChecked(True)

        layout.addStretch()

    def _on_btn_clicked(self, id):
        self.tab_changed.emit(id)

