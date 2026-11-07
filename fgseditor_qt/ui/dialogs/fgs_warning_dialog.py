from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QPushButton,
    QSizePolicy,
)
from PySide6.QtGui import QFont


class NonStandardFgsDialog(QDialog):
    def __init__(self, parent=None, warnings: list[str] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("FGS Syntax Warning")
        self.setMinimumSize(560, 360)
        self.resize(600, 400)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header_layout = QHBoxLayout()
        header_icon = QLabel("⚠️")
        header_icon.setStyleSheet("font-size: 26px; margin-right: 6px;")
        header_layout.addWidget(header_icon, stretch=0)

        header_text = QLabel(
            "The loaded FGS file contains non-standard syntax.\n"
            "The table was normalized to comply with AFGS1:"
        )
        header_text.setStyleSheet("font-size: 13px; font-weight: bold; color: #f59e0b;")
        header_text.setWordWrap(True)
        header_layout.addWidget(header_text, stretch=1)
        layout.addLayout(header_layout)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        font = QFont("Consolas, Courier New, Monospace")
        font.setPointSize(10)
        self.log_view.setFont(font)
        self.log_view.setStyleSheet(
            "background-color: #111111; color: #e0e0e0; border: 1px solid #333333; border-radius: 4px; padding: 6px;"
        )

        warning_lines = warnings or ["No specific warnings recorded."]
        formatted_content = "\n".join(f"• {w}" for w in warning_lines)
        self.log_view.setPlainText(formatted_content)
        layout.addWidget(self.log_view, stretch=1)

        note_lbl = QLabel(
            "The normalized table is ready for editing and export."
        )
        note_lbl.setStyleSheet("color: #888888; font-size: 11px; font-style: italic;")
        layout.addWidget(note_lbl)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)

        ok_btn = QPushButton("OK")
        ok_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        ok_btn.setMinimumWidth(90)
        ok_btn.setStyleSheet(
            "background-color: #2563eb; color: white; font-weight: bold; padding: 6px 14px; border-radius: 4px;"
        )
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)


def ask_static_dynamic_mode(parent=None, title: str = "Binary Export Mode") -> bool | None:
    from PySide6.QtCore import Qt

    mode_dialog = QDialog(parent)
    mode_dialog.setWindowTitle(title)
    mode_dialog.setMinimumWidth(460)
    layout = QVBoxLayout(mode_dialog)
    layout.setSpacing(12)

    title_lbl = QLabel("<b>Select binary export mode:</b>")
    title_lbl.setTextFormat(Qt.RichText)
    layout.addWidget(title_lbl)

    static_desc = QLabel("<b>Static</b> — Constant seed across frames.")
    static_desc.setWordWrap(True)
    layout.addWidget(static_desc)

    dynamic_desc = QLabel("<b>Dynamic</b> — Unique seed per frame.")
    dynamic_desc.setWordWrap(True)
    layout.addWidget(dynamic_desc)

    btn_layout = QHBoxLayout()
    static_btn = QPushButton("Static")
    static_btn.setMinimumWidth(90)
    dynamic_btn = QPushButton("Dynamic")
    dynamic_btn.setMinimumWidth(90)
    cancel_btn = QPushButton("Cancel")
    cancel_btn.setMinimumWidth(80)
    btn_layout.addWidget(static_btn)
    btn_layout.addWidget(dynamic_btn)
    btn_layout.addWidget(cancel_btn)
    layout.addLayout(btn_layout)

    result = [None]

    def _pick_static():
        result[0] = True
        mode_dialog.accept()

    def _pick_dynamic():
        result[0] = False
        mode_dialog.accept()

    static_btn.clicked.connect(_pick_static)
    dynamic_btn.clicked.connect(_pick_dynamic)
    cancel_btn.clicked.connect(mode_dialog.reject)

    if mode_dialog.exec() != QDialog.Accepted or result[0] is None:
        return None
    return result[0]

